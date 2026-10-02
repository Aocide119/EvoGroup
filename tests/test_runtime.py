import json

import pytest
from conftest import ScriptedProvider

from evog.app import Application
from evog.demo import DemoProvider
from evog.errors import ContractError, ProviderError, RunFailed
from evog.harness import Harness
from evog.models import AnswerDraft
from evog.providers import ModelReply, ToolCall
from evog.runtime import interact, validate_answer


def test_complete_offline_interaction_reflects_before_feedback(store, settings):
    answer = interact(store, DemoProvider(), settings, "Latest release?", ["demo-team"])
    assert "January 15" in answer.text
    assert answer.citations == ["demo-team/002"]
    assert answer.reflection is not None
    assert store.runs(answer.revision_id)[0]["outcome"] is None
    assert [event.kind for event in store.events(answer.run_id)][-2:] == ["answer", "reflection"]


def test_forged_citation_is_repaired_by_real_delivery(store, settings):
    forged = ModelReply(
        content=json.dumps(
            {"text": "claim", "confidence": 0.9, "status": "complete", "citations": ["private/1"]}
        )
    )
    search = ModelReply(
        tool_calls=[ToolCall(id="s", name="grep_search", arguments={"terms": ["changed"]})]
    )
    supported = ModelReply(
        content=json.dumps(
            {
                "text": "January 15",
                "confidence": 0.9,
                "status": "complete",
                "citations": ["demo-team/002"],
            }
        )
    )
    provider = ScriptedProvider(forged, search, supported)
    answer = interact(store, provider, settings, "Latest release?", ["demo-team"])
    assert answer.citations == ["demo-team/002"]
    assert any(event.data.get("code") == "answer_contract" for event in store.events(answer.run_id))


def test_invalid_final_answers_are_selected_contract_failures(store, settings):
    provider = ScriptedProvider(
        *[ModelReply(content="not JSON") for _ in range(settings.max_turns)]
    )
    with pytest.raises(RunFailed) as failure:
        interact(store, provider, settings, "Question", ["demo-team"])
    assert store.run(failure.value.run_id)["status"] == "contract_failed"
    assert provider.calls[-1][1] == []
    from evog.analysis import select_experience

    selection = select_experience(store, settings, store.harness().id)
    assert selection["selected"] == [failure.value.run_id]
    assert selection["coverage"]["contract_failures"] == 1
    assert selection["coverage"]["incidents"] == 0


def test_provider_failure_preserves_run_and_safe_error(store, settings):
    provider = ScriptedProvider(ProviderError("Provider transport failed"))
    with pytest.raises(RunFailed) as failure:
        interact(store, provider, settings, "Question", ["demo-team"])
    assert store.events(failure.value.run_id)[-1].data == {"code": "provider_error"}
    assert store.run(failure.value.run_id)["status"] == "provider_failed"


def test_tool_filesystem_failure_has_separate_status(store, settings, monkeypatch):
    from evog.tools import Tools

    def fail(*_):
        raise PermissionError("private filesystem details")

    monkeypatch.setattr(Tools, "execute", fail)
    provider = ScriptedProvider(
        ModelReply(tool_calls=[ToolCall(id="s", name="list_files", arguments={})])
    )
    with pytest.raises(RunFailed) as failure:
        interact(store, provider, settings, "Question", ["demo-team"])
    assert store.run(failure.value.run_id)["status"] == "tool_failed"
    assert store.events(failure.value.run_id)[-1].data == {"code": "tool_execution"}


def test_tool_only_model_at_turn_boundary_is_budget_exhaustion(store, settings):
    reply = ModelReply(tool_calls=[ToolCall(id="s", name="list_files", arguments={})])
    provider = ScriptedProvider(*[reply for _ in range(settings.max_turns)])
    with pytest.raises(RunFailed) as failure:
        interact(store, provider, settings, "Question", ["demo-team"])
    assert store.run(failure.value.run_id)["status"] == "budget_exhausted"


def test_context_exhaustion_is_distinct_from_provider_failure(store, settings, monkeypatch):
    # Lower the budget after settings validation to exercise the boundary before any model call.
    monkeypatch.setattr(settings, "max_context_chars", 1)
    provider = ScriptedProvider()
    with pytest.raises(RunFailed) as failure:
        interact(store, provider, settings, "Question", ["demo-team"])
    assert store.run(failure.value.run_id)["status"] == "budget_exhausted"
    assert not provider.calls


def test_reflection_failure_preserves_supported_answer(store, settings, empty_reply):
    provider = ScriptedProvider(empty_reply, ProviderError("unavailable"))
    answer = interact(store, provider, settings, "Question", ["demo-team"])
    assert answer.reflection is None
    assert store.run(answer.run_id)["status"] == "completed"


def test_fixed_complete_citation_guard_survives_policy_changes(store):
    contents = store.harness().contents
    contents["prompts/group.md"] = "Answer without evidence."
    draft = AnswerDraft(text="unsupported", confidence=0.9, status="complete", citations=[])
    with pytest.raises(ContractError, match="source citations"):
        validate_answer(draft, Harness(contents), set())


def test_intervention_answer_limit_is_effective(store):
    contents = store.harness().contents
    contents["interventions.json"] = (
        '{"max_answer_chars":256,"max_citations":1,"require_citations_for_partial":true}'
    )
    draft = AnswerDraft(
        text="x" * 257, confidence=0.9, status="complete", citations=["demo-team/002"]
    )
    with pytest.raises(ContractError, match="output limits"):
        validate_answer(draft, Harness(contents), {"demo-team/002"})


def test_tool_call_budget_is_enforced(store, settings, empty_reply):
    settings.max_tool_calls = 1
    batch = ModelReply(
        tool_calls=[
            ToolCall(id="1", name="grep_search", arguments={"terms": ["release"]}),
            ToolCall(id="2", name="write_file", arguments={"path": "memory/x.md", "content": "no"}),
        ]
    )
    reflection = ModelReply(
        content='{"searched":["release"],"evidence_found":"some","unresolved":["question"],"limitation":"budget"}'
    )
    provider = ScriptedProvider(batch, empty_reply, reflection)
    answer = interact(store, provider, settings, "Question", ["demo-team"])
    results = [event for event in store.events(answer.run_id) if event.kind == "tool"]
    assert results[0].data["result"]["ok"]
    assert not results[1].data["result"]["ok"]


def test_command_orchestration_and_empty_analysis_need_no_credentials(tmp_path):
    with Application(tmp_path / "workspace") as group:
        report = group.analyze()
        assert report.coverage["total"] == 0
        assert group.propose(report).changes == []
