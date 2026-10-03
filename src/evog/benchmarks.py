"""CLI benchmark execution over the product runtime, with isolated question notes."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from evog import analysis, evolution
from evog.app import Application
from evog.benchmark_data import BenchmarkName, Corpus, Episode, load_corpus, load_episodes
from evog.benchmark_judge import score
from evog.errors import ContractError, EvoGError, RunFailed
from evog.harness import Harness
from evog.io import atomic_write, dumps, fingerprint
from evog.runtime import interact

Progress = Callable[[str], None]


def _write(path: Path, payload: dict) -> None:
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def metrics(results: list[dict]) -> dict:
    passed = sum(row["passed"] is True for row in results)
    failed = sum(row["passed"] is False for row in results)
    total = len(results)
    usage: dict[str, int] = {}
    for row in results:
        for stage in ("agent_usage", "judge_usage"):
            for key, value in row.get(stage, {}).items():
                usage[key] = usage.get(key, 0) + value
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "unscored": total - passed - failed,
        "pass_rate": passed / total if total else None,
        "scored_pass_rate": passed / (passed + failed) if passed + failed else None,
        "tool_calls": sum(row.get("tool_calls", 0) for row in results),
        "usage": usage,
    }


def compare(before: list[dict], after: list[dict]) -> dict:
    left, right = (
        {row["episode_id"]: row for row in before},
        {row["episode_id"]: row for row in after},
    )
    if len(left) != len(before) or len(right) != len(after) or left.keys() != right.keys():
        raise ContractError("Paired comparison requires unique, identical episode IDs")
    counts = {
        name: 0
        for name in ("fail_to_pass", "pass_to_fail", "pass_to_pass", "fail_to_fail", "unscored")
    }
    for key in left:
        a, b = left[key]["passed"], right[key]["passed"]
        if a is None or b is None:
            counts["unscored"] += 1
        else:
            counts[("pass" if a else "fail") + "_to_" + ("pass" if b else "fail")] += 1
    return {"paired_episodes": len(left), **counts}


def evaluate(
    app: Application,
    episodes: list[Episode],
    corpora: dict[str, Corpus],
    harness: Harness,
    *,
    batch_id: str,
    stage: str,
    progress: Progress,
    feedback: bool,
    checkpoint: Callable[[list[dict]], None],
) -> list[dict]:
    results = []
    for index, episode in enumerate(episodes, 1):
        progress(f"{stage} {index}/{len(episodes)}: {episode.episode_id}")
        started = time.monotonic()
        row: dict[str, Any] = {
            "episode_id": episode.episode_id,
            "scope": episode.scope,
            "question_type": episode.question_type,
            "question": episode.question,
            "gold": episode.gold,
            "passed": None,
            "revision_id": harness.id,
        }
        try:
            answer = interact(
                app.store,
                app.provider,
                app.settings,
                episode.prompt(),
                corpora[episode.scope].group_ids,
                harness,
                memory_session=f"{batch_id}/{stage}/{episode.episode_id}",
            )
            row.update(
                {
                    "run_id": answer.run_id,
                    "answer": answer.model_dump(mode="json"),
                    "status": "completed",
                }
            )
            judged = score(app.provider, episode, answer.text)
            row.update(
                {
                    "passed": judged["passed"],
                    "judge": judged,
                    "judge_usage": judged.get("usage", {}),
                }
            )
            if feedback and judged["passed"] is not None:
                app.feedback(
                    answer.run_id,
                    "accepted" if judged["passed"] else "rejected",
                    source=f"{episode.benchmark}-official",
                )
        except RunFailed as exc:
            row.update(
                {
                    "run_id": exc.run_id,
                    "status": app.store.run(exc.run_id)["status"],
                    "error": str(exc),
                }
            )
        except EvoGError as exc:
            row.update({"status": "failed", "error": str(exc)})
        events = app.store.events(row["run_id"]) if row.get("run_id") else []
        usage: dict[str, int] = {}
        for event in events:
            if event.kind in ("model", "reflection"):
                for key, value in event.data.get("usage", {}).items():
                    usage[key] = usage.get(key, 0) + value
        row.update(
            {
                "seconds": round(time.monotonic() - started, 3),
                "agent_usage": usage,
                "tool_calls": sum(event.kind == "tool" for event in events),
            }
        )
        results.append(row)
        checkpoint(results)
        progress(f"  status={row['status']} passed={row['passed']} tools={row['tool_calls']}")
    return results


def run(
    app: Application,
    name: BenchmarkName,
    root: Path,
    *,
    output: Path,
    topics: list[str] | None = None,
    domains: list[str] | None = None,
    question_types: list[str] | None = None,
    limit: int | None = 2,
    episode_file: Path | None = None,
    assumed_timezone: str = "UTC",
    cycle: bool = False,
    validation_episode_file: Path | None = None,
    progress: Progress = lambda _: None,
) -> dict:
    if output.exists():
        raise ContractError("Output already exists; use a new path to preserve prior results")
    episodes = load_episodes(
        name,
        root,
        topics=topics,
        domains=domains,
        question_types=question_types,
        limit=limit,
        episode_file=episode_file,
    )
    validation = None
    if validation_episode_file:
        validation = load_episodes(
            name,
            root,
            topics=topics,
            domains=domains,
            question_types=question_types,
            episode_file=validation_episode_file,
        )
        if {row.episode_id for row in episodes} & {row.episode_id for row in validation}:
            raise ContractError("Validation and evolution episode IDs must be disjoint")
    batch_id = uuid4().hex
    payload: dict[str, Any] = {
        "id": batch_id,
        "benchmark": name,
        "status": "preparing",
        "model": app.settings.model,
        "base_url": app.settings.base_url,
        "assumed_timezone": assumed_timezone,
        "episode_ids": [row.episode_id for row in episodes],
        "selection_fingerprint": fingerprint([row.model_dump() for row in episodes]),
        "judge_protocol": "official",
        "note_isolation": "fresh-per-question-per-stage",
        "validation_kind": "held_out" if validation else "same_sample_regression",
        "corpora": {},
    }
    _write(output, payload)
    corpora: dict[str, Corpus] = {}
    all_episodes = episodes + (validation or [])
    for scope in sorted({episode.scope for episode in all_episodes}):
        corpus = load_corpus(name, root, scope, assumed_timezone)
        imported = app.ingest(iter(corpus.messages))
        corpora[scope] = corpus
        payload["corpora"][scope] = {
            "fingerprint": corpus.fingerprint,
            "messages": len(corpus.messages),
            "imported": imported,
            "groups": len(corpus.group_ids),
        }
        progress(
            f"Imported {scope}: {len(corpus.messages)} messages / {len(corpus.group_ids)} groups"
        )
    # Include source attribution and domain metadata in the evaluation harness.
    active = app.store.harness()
    if not active.representation.include_metadata:
        contents = dict(active.contents)
        contents["representation.json"] = dumps({"include_metadata": True})
        source_view = Harness(contents)
        app.store.activate(source_view, active.id, "benchmark-source-view", "structural")
        active = source_view
    payload["parent_revision_id"] = active.id

    def execute(
        stage: str, selected: list[Episode], harness: Harness, attach_feedback: bool
    ) -> list[dict]:
        payload["status"] = stage

        def checkpoint(rows: list[dict]) -> None:
            payload[stage] = {"results": rows, "metrics": metrics(rows)}
            _write(output, payload)

        return evaluate(
            app,
            selected,
            corpora,
            harness,
            batch_id=batch_id,
            stage=stage,
            progress=progress,
            feedback=attach_feedback,
            checkpoint=checkpoint,
        )

    baseline = execute("baseline", episodes, active, True)
    if cycle:
        payload["status"] = "analysis"
        _write(output, payload)
        progress("Analyzing selected experience")
        report = analysis.analyze(app.store, app.provider, app.settings, active.id)
        payload["analysis"] = report.model_dump(mode="json")
        _write(output, payload)
        if report.incomplete:
            payload["evolution_status"] = "incomplete_analysis"
        else:
            progress("Proposing an evidence-linked harness revision")
            plan = app.propose(report)
            payload["plan"] = plan.model_dump(mode="json")
            _write(output, payload)
            if plan.changes:
                revised = evolution.candidate(app.store, plan, report)
                # Store the candidate for trace lookup without activating it.
                with app.store.connect() as db:
                    db.execute(
                        "INSERT OR IGNORE INTO revisions VALUES(?,?,?,?,?)",
                        (revised.id, dumps(revised.contents), active.id, plan.id, "structural"),
                    )
                checking = validation or episodes
                before = (
                    execute("validation_baseline", checking, active, False)
                    if validation
                    else baseline
                )
                after = execute("candidate", checking, revised, False)
                paired = compare(before, after)
                payload["comparison"] = paired
                # A small regression sample validates plumbing, not full benchmark quality.
                accepted = paired["unscored"] == 0 and paired["pass_to_fail"] == 0
                if accepted:
                    activated = app.apply(plan.id, validator=lambda _: True)
                    payload["activated"] = activated.model_dump(mode="json")
                    payload["evolution_status"] = "activated"
                else:
                    payload["evolution_status"] = "regression_rejected"
            else:
                payload["evolution_status"] = "no_supported_change"
    payload["status"] = "completed"
    _write(output, payload)
    return payload
