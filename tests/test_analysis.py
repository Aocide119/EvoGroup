import json
from uuid import uuid4

import pytest
from conftest import ScriptedProvider

from evog.analysis import InspectArgs, TraceAccess, analyze, diagnose, select_experience
from evog.demo import DemoProvider
from evog.errors import ContractError
from evog.models import Answer, EvidenceRef, Feedback
from evog.providers import ModelReply, ToolCall
from evog.runtime import interact


def create_run(store, confidence, outcome=None, status="completed"):
    run_id = uuid4().hex
    revision = store.harness().id
    store.start_run(run_id, revision, "A question", ["demo-team"])
    answer = (
        Answer(
            text="answer",
            confidence=confidence,
            status="complete",
            citations=["demo-team/001"],
            run_id=run_id,
            revision_id=revision,
        )
        if status == "completed"
        else None
    )
    store.finish_run(run_id, answer, status)
    if outcome:
        store.feedback(Feedback(run_id=run_id, outcome=outcome, source="test"))
    return run_id


def test_all_confidence_feedback_cells_and_unknowns_remain_distinct(store, settings):
    run_ids = [
        create_run(store, confidence, outcome)
        for confidence, outcome in [
            (0.9, "accepted"),
            (0.9, "rejected"),
            (0.5, "accepted"),
            (0.1, "rejected"),
            (0.9, None),
            (0.1, None),
        ]
    ]
    create_run(store, 0.1, status="incident")
    selected = select_experience(store, settings, store.harness().id)
    assert all(
        selected["coverage"][label] == 1
        for label in ["CC", "CW", "UC", "UW", "unjudged_high", "unjudged_low", "incidents"]
    )
    assert selected["coverage"]["total"] == 7
    assert set(selected["selected"]) == {run_ids[1], run_ids[2], run_ids[3], run_ids[5]}
    assert selected["controls"] == [run_ids[0]]


def test_latest_feedback_overrides_without_deleting_prior_feedback(store, settings):
    run_id = create_run(store, 0.9, "accepted")
    store.feedback(Feedback(run_id=run_id, outcome="rejected", source="correction"))
    assert select_experience(store, settings, store.harness().id)["coverage"]["CW"] == 1
    with store.connect() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM feedback WHERE run_id=?", (run_id,)).fetchone()[0] == 2
        )


def test_selection_reports_coverage_before_bounding(store, settings):
    for _ in range(3):
        create_run(store, 0.1)
    settings.analysis_max_runs = 1
    result = select_experience(store, settings, store.harness().id)
    assert result["coverage"]["eligible"] == 3
    assert result["coverage"]["selected"] == 1
    assert len(result["selected"]) == 1


def test_progressive_inspection_requires_scope_and_reports_exact_ranges(store):
    run_id = create_run(store, 0.1)
    store.event(run_id, "tool", {"name": "read_file", "result": {"text": "abcdefghij"}})
    access = TraceAccess(store, [run_id])
    first = access.inspect(
        InspectArgs(run_id=run_id, event_index=0, field_path="/result/text", limit=4)
    )
    assert first["content"] == "abcd"
    assert first["evidence_ref"]["end_char"] == 4
    assert first["truncated"] and first["next_start_char"] == 4
    second = access.inspect(
        InspectArgs(run_id=run_id, event_index=0, field_path="/result/text", start_char=4)
    )
    assert second["content"] == "efghij" and not second["truncated"]
    with pytest.raises(ContractError):
        access.inspect(InspectArgs(run_id="other", event_index=0))
    with pytest.raises(ContractError):
        access.inspect(InspectArgs(run_id=run_id, event_index=0, field_path="/missing"))


def test_diagnosis_rejects_an_uninspected_event(store, settings):
    run_id = create_run(store, 0.1)
    store.event(run_id, "answer", {"text": "answer"})
    reply = ModelReply(
        content=json.dumps(
            {
                "run_id": run_id,
                "query_type": "retrieval",
                "category": "retrieval",
                "earliest_break": "unseen",
                "cause": "unseen",
                "condensed_rationale": "unseen",
                "actionable_implication": "unseen",
                "uncertainty": "unknown",
                "evidence": [{"run_id": run_id, "event_index": 0, "end_char": 10}],
            }
        )
    )
    with pytest.raises(ContractError, match="did not inspect"):
        diagnose(store, ScriptedProvider(reply), settings, run_id, [], TraceAccess(store, [run_id]))


def test_analysis_preserves_incomplete_diagnoses(store, settings):
    run_id = create_run(store, 0.1)
    report = analyze(store, ScriptedProvider(ModelReply(content="invalid")), settings)
    assert run_id in report.incomplete
    assert report.diagnoses == [] and report.findings == []


def test_demo_analysis_inspects_evidence_and_preserves_findings(store, settings):
    answer = interact(store, DemoProvider(), settings, "Latest release?", ["demo-team"])
    store.feedback(Feedback(run_id=answer.run_id, outcome="accepted", source="test"))
    report = analyze(store, DemoProvider(), settings)
    assert len(report.diagnoses) == 1 and len(report.findings) == 1
    ref = report.findings[0].evidence[0]
    assert ref.field_path == "/result"
    assert store.events(ref.run_id)[ref.event_index].kind == "tool"
    assert report.incomplete == {}


def test_running_interactions_are_distinct_from_incidents(store, settings):
    create_run(store, 0.1, status="running")
    selection = select_experience(store, settings, store.harness().id)
    assert selection["coverage"]["unfinished"] == 1
    assert selection["coverage"]["incidents"] == 0
    assert selection["selected"] == []


def test_synthesis_cannot_introduce_uninspected_evidence(store, settings):
    answer = interact(store, DemoProvider(), settings, "Latest release?", ["demo-team"])

    class ForgedSynthesis(DemoProvider):
        def complete(self, messages, tools):
            reply = super().complete(messages, tools)
            if "synthesize EvoGroup" in messages[0]["content"]:
                data = json.loads(reply.content)
                data["findings"][0]["evidence"][0]["event_index"] = 999
                return ModelReply(content=json.dumps(data))
            return reply

    report = analyze(store, ForgedSynthesis(), settings)
    assert answer.run_id in report.selected_run_ids
    assert report.diagnoses and not report.findings
    assert "synthesis" in report.incomplete


@pytest.mark.parametrize("start_char", [0, 3])
def test_inspection_cannot_deliver_empty_evidence(store, start_char):
    run_id = create_run(store, 0.1)
    store.event(run_id, "answer", {"text": "" if start_char == 0 else "abc"})
    access = TraceAccess(store, [run_id])
    with pytest.raises(ContractError, match="nonempty"):
        access.inspect(
            InspectArgs(run_id=run_id, event_index=0, field_path="/text", start_char=start_char)
        )
    assert not access.delivered


@pytest.mark.parametrize("start,end", [(0, 0), (3, 3), (4, 2)])
def test_empty_or_reversed_evidence_ref_is_invalid(start, end):
    with pytest.raises(ValueError, match="nonempty"):
        EvidenceRef(run_id="run", event_index=0, start_char=start, end_char=end)


@pytest.mark.parametrize("pointer", ["/rows/-1", "/rows/-", "/rows/+0", "/rows/01", "/rows/١"])
def test_trace_pointer_rejects_nonstandard_array_indices(store, pointer):
    run_id = create_run(store, 0.1)
    store.event(run_id, "answer", {"rows": ["first", "last"]})
    with pytest.raises(ContractError):
        TraceAccess(store, [run_id]).inspect(
            InspectArgs(run_id=run_id, event_index=0, field_path=pointer)
        )


def test_pointer_escapes_array_reads_and_literal_object_keys(store):
    run_id = create_run(store, 0.1)
    store.event(run_id, "answer", {"a/b": {"~key": ["first", "last"]}, "-1": "literal"})
    access = TraceAccess(store, [run_id])
    assert (
        access.inspect(InspectArgs(run_id=run_id, event_index=0, field_path="/a~1b/~0key/1"))[
            "content"
        ]
        == "last"
    )
    assert (
        access.inspect(InspectArgs(run_id=run_id, event_index=0, field_path="/-1"))["content"]
        == "literal"
    )
    with pytest.raises(ContractError, match="escape"):
        access.inspect(InspectArgs(run_id=run_id, event_index=0, field_path="/a~2b"))


def test_failed_output_contract_can_be_diagnosed_without_answer_or_confidence(store, settings):
    run_id = create_run(store, 0.1, status="contract_failed")
    store.event(run_id, "error", {"code": "answer_contract"})

    def checked_inspection(messages, tools):
        supplied = json.loads(messages[1]["content"])
        assert supplied["status"] == "contract_failed"
        assert supplied["subjective_confidence"] is None
        assert supplied["feedback_outcome"] == "unjudged"
        return ModelReply(
            tool_calls=[
                ToolCall(
                    id="i", name="inspect_trace", arguments={"run_id": run_id, "event_index": 0}
                )
            ]
        )

    def checked_diagnosis(messages, tools):
        ref = json.loads(messages[-1]["content"])["evidence_ref"]
        return ModelReply(
            content=json.dumps(
                {
                    "run_id": run_id,
                    "query_type": "answer delivery",
                    "category": "delivery",
                    "earliest_break": "output",
                    "cause": "invalid output",
                    "condensed_rationale": "output contract failed",
                    "actionable_implication": "clarify format",
                    "evidence": [ref],
                    "uncertainty": "one observation",
                }
            )
        )

    provider = ScriptedProvider(
        checked_inspection, checked_diagnosis, ModelReply(content='{"findings":[]}')
    )
    report = analyze(store, provider, settings)
    assert report.selected_run_ids == [run_id]
    assert len(report.diagnoses) == 1
    assert not report.incomplete
