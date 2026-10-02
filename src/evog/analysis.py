"""Confidence selection, addressable trace inspection, and bucketed synthesis."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import Field

from evog.config import Settings
from evog.errors import ContractError, EvoGError
from evog.harness import prompt
from evog.io import dumps
from evog.models import AnalysisReport, Diagnosis, EvidenceRef, Finding, Record
from evog.pointers import resolve_pointer
from evog.providers import Provider, assistant_message
from evog.store import Store


class InspectArgs(Record):
    run_id: str
    event_index: int = Field(ge=0)
    field_path: str = ""
    start_char: int = Field(default=0, ge=0)
    limit: int = Field(default=8000, ge=1, le=12000)


class SearchTraceArgs(Record):
    run_id: str
    term: str = Field(min_length=1, max_length=256)
    offset: int = Field(default=0, ge=0)


class Findings(Record):
    findings: list[Finding] = Field(max_length=30)


def ref_key(ref: EvidenceRef) -> str:
    return dumps(ref.model_dump())


class TraceAccess:
    def __init__(self, store: Store, allowed: list[str]):
        self.events = {run: store.events(run) for run in allowed}
        self.delivered: set[str] = set()

    def summary(self, run_id: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "events": [
                {
                    "index": event.index,
                    "kind": event.kind,
                    "chars": len(dumps(event.data)),
                    **({"tool_name": event.data["name"]} if event.kind == "tool" else {}),
                }
                for event in self.events[run_id]
            ],
        }

    def inspect(self, args: InspectArgs) -> dict[str, Any]:
        if args.run_id not in self.events:
            raise ContractError("Trace is outside the analysis scope")
        events = self.events[args.run_id]
        if args.event_index >= len(events):
            raise ContractError("Event index is out of range")
        event = events[args.event_index]
        value = resolve_pointer(event.data, args.field_path)
        text = value if isinstance(value, str) else dumps(value)
        if args.start_char >= len(text):
            raise ContractError("No nonempty evidence at start_char")
        end = min(args.start_char + args.limit, len(text))
        ref = EvidenceRef(
            run_id=args.run_id,
            event_index=event.index,
            field_path=args.field_path,
            start_char=args.start_char,
            end_char=end,
        )
        self.delivered.add(ref_key(ref))
        return {
            "evidence_ref": ref.model_dump(),
            "kind": event.kind,
            "content": text[args.start_char : end],
            "total_chars": len(text),
            "truncated": end < len(text),
            "next_start_char": end if end < len(text) else None,
        }

    def search(self, args: SearchTraceArgs) -> dict[str, Any]:
        if args.run_id not in self.events:
            raise ContractError("Trace is outside the analysis scope")
        matching = [
            event
            for event in self.events[args.run_id]
            if args.term.casefold() in dumps(event.data).casefold()
        ]
        selected = matching[args.offset : args.offset + 10]
        next_offset = args.offset + len(selected)
        return {
            "events": [{"index": event.index, "kind": event.kind} for event in selected],
            "total": len(matching),
            "next_offset": next_offset if next_offset < len(matching) else None,
            "note": "Search locates events; inspect_trace is required before citing them.",
        }

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "inspect_trace":
            return self.inspect(InspectArgs.model_validate(arguments))
        if name == "search_trace":
            return self.search(SearchTraceArgs.model_validate(arguments))
        raise ContractError("Unknown analysis tool")


def analysis_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": model.model_json_schema(),
            },
        }
        for name, model, description in (
            (
                "inspect_trace",
                InspectArgs,
                "Inspect an event or JSON-pointer field in bounded character ranges; cite the returned evidence_ref exactly.",
            ),
            (
                "search_trace",
                SearchTraceArgs,
                "Locate event indices with a literal anchor. Search results are not inspected evidence.",
            ),
        )
    ]


def select_experience(store: Store, settings: Settings, revision_id: str) -> dict[str, Any]:
    coverage = {
        name: 0
        for name in (
            "total",
            "incidents",
            "provider_incidents",
            "tool_incidents",
            "contract_failures",
            "budget_exhausted",
            "unfinished",
            "CC",
            "CW",
            "UC",
            "UW",
            "unjudged_high",
            "unjudged_low",
        )
    }
    selected, controls = [], []
    for run in store.runs(revision_id):
        coverage["total"] += 1
        if run["status"] != "completed":
            label = {
                "contract_failed": "contract_failures",
                "budget_exhausted": "budget_exhausted",
                "provider_failed": "provider_incidents",
                "tool_failed": "tool_incidents",
                "incident": "incidents",
            }.get(run["status"], "unfinished")
            coverage[label] += 1
            if run["status"] in ("contract_failed", "budget_exhausted"):
                selected.append(run["id"])
            elif run["status"] in ("provider_failed", "tool_failed"):
                coverage["incidents"] += 1
            continue
        low = run["answer"]["confidence"] <= settings.confidence_threshold
        outcome = run["outcome"]
        label = (
            ("U" if low else "C") + ("C" if outcome == "accepted" else "W")
            if outcome
            else ("unjudged_low" if low else "unjudged_high")
        )
        coverage[label] += 1
        if label in ("CW", "UC", "UW", "unjudged_low"):
            selected.append(run["id"])
        elif label == "CC":
            controls.append(run["id"])
    coverage["eligible"] = len(selected)
    coverage["selected"] = min(len(selected), settings.analysis_max_runs)
    coverage["controls"] = min(len(controls), 2)
    return {
        "coverage": coverage,
        "selected": selected[: settings.analysis_max_runs],
        "controls": controls[:2],
    }


def diagnose(
    store: Store,
    provider: Provider,
    settings: Settings,
    run_id: str,
    controls: list[str],
    access: TraceAccess,
) -> Diagnosis:
    run = store.run(run_id)
    supplied = {
        "run_id": run_id,
        "question": run["question"],
        "status": run["status"],
        "subjective_confidence": run["answer"]["confidence"] if run["answer"] else None,
        "reflection": run["answer"].get("reflection") if run["answer"] else None,
        "trace": access.summary(run_id),
        "controls": [
            {"question": store.run(control)["question"], "trace": access.summary(control)}
            for control in controls
        ],
    }
    # Only a categorical feedback signal is exposed. No hidden expected answer exists.
    row = next(row for row in store.runs(run["revision_id"]) if row["id"] == run_id)
    supplied["feedback_outcome"] = row["outcome"] or "unjudged"
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": prompt("analyze") + "\nSchema: " + dumps(Diagnosis.model_json_schema()),
        },
        {"role": "user", "content": dumps(supplied)},
    ]
    inspected_here: set[str] = set()
    for turn in range(settings.analysis_turns):
        if len(dumps(messages)) > settings.max_context_chars:
            raise ContractError("Analysis context budget exhausted")
        reply = provider.complete(
            messages, analysis_tools() if turn < settings.analysis_turns - 1 else []
        )
        messages.append(assistant_message(reply))
        if reply.tool_calls:
            if turn == settings.analysis_turns - 1:
                raise ContractError("No diagnosis returned at the analysis budget boundary")
            for call in reply.tool_calls:
                try:
                    result = access.execute(call.name, call.arguments)
                    if "evidence_ref" in result:
                        inspected_here.add(dumps(result["evidence_ref"]))
                except (EvoGError, ValueError):
                    result = {"error": "Invalid analysis request; check trace scope and schema"}
                messages.append({"role": "tool", "tool_call_id": call.id, "content": dumps(result)})
            continue
        diagnosis = Diagnosis.model_validate_json(reply.content)
        if diagnosis.run_id != run_id:
            raise ContractError("Diagnosis changed its target run")
        if any(ref_key(ref) not in inspected_here for ref in diagnosis.evidence):
            raise ContractError("Diagnosis cites trace fields or ranges it did not inspect")
        if not any(ref.run_id == run_id for ref in diagnosis.evidence):
            raise ContractError("Diagnosis must inspect the target interaction")
        return diagnosis
    raise ContractError("Analysis turn budget exhausted")


def analyze(
    store: Store, provider: Provider | None, settings: Settings, revision_id: str | None = None
) -> AnalysisReport:
    revision_id = store.harness(revision_id).id
    selection = select_experience(store, settings, revision_id)
    selected, controls = selection["selected"], selection["controls"]
    access = TraceAccess(store, [*selected, *controls])
    diagnoses, incomplete = [], {}
    for run_id in selected:
        try:
            if provider is None:
                raise ContractError("A provider is required for selected experience analysis")
            diagnoses.append(diagnose(store, provider, settings, run_id, controls, access))
        except (EvoGError, ValueError):
            incomplete[run_id] = "Diagnosis unavailable or failed evidence validation"
    findings = []
    if diagnoses:
        assert provider is not None
        buckets: dict[str, list[dict[str, Any]]] = {}
        allowed_refs = set()
        for diagnosis in diagnoses:
            buckets.setdefault(diagnosis.query_type, []).append(diagnosis.model_dump())
            allowed_refs.update(ref_key(ref) for ref in diagnosis.evidence)
        synthesis = {
            "coverage": selection["coverage"],
            "buckets": buckets,
            "incomplete": incomplete,
        }
        if len(dumps(synthesis)) <= settings.max_context_chars:
            try:
                reply = provider.complete(
                    [
                        {
                            "role": "system",
                            "content": prompt("synthesize")
                            + "\nSchema: "
                            + dumps(Findings.model_json_schema()),
                        },
                        {"role": "user", "content": dumps(synthesis)},
                    ],
                    [],
                )
                findings = Findings.model_validate_json(reply.content).findings
                if len({finding.id for finding in findings}) != len(findings):
                    raise ContractError("Finding IDs must be unique")
                if any(
                    ref_key(ref) not in allowed_refs
                    for finding in findings
                    for ref in finding.evidence
                ):
                    raise ContractError("Finding references evidence outside inspected diagnoses")
            except (EvoGError, ValueError):
                findings = []
                incomplete["synthesis"] = "Synthesis unavailable or failed evidence validation"
        else:
            incomplete["synthesis"] = "Synthesis context budget exhausted"
    report = AnalysisReport(
        id=uuid4().hex,
        revision_id=revision_id,
        coverage=selection["coverage"],
        selected_run_ids=selected,
        control_run_ids=controls,
        diagnoses=diagnoses,
        findings=findings,
        incomplete=incomplete,
    )
    store.save_artifact(report.id, "analysis", report.model_dump(mode="json"))
    return report
