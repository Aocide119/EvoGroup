import pytest

from evog.analysis import analyze
from evog.app import Application
from evog.demo import DemoProvider
from evog.errors import ConflictError, ContractError
from evog.evolution import apply, candidate, propose
from evog.harness import Harness
from evog.models import Feedback
from evog.runtime import interact


def prepare(store, settings):
    provider = DemoProvider()
    answer = interact(store, provider, settings, "Latest release?", ["demo-team"])
    store.feedback(Feedback(run_id=answer.run_id, outcome="accepted", source="test"))
    report = analyze(store, provider, settings)
    plan = propose(store, provider, settings, report)
    return report, plan


def test_revision_activate_and_rollback_preserve_sources_and_trace(store, settings):
    report, plan = prepare(store, settings)
    prior = store.harness().id
    activated = apply(store, plan.id)
    assert activated.validation == "structural"
    assert "skills/status-verification.md" in store.harness().contents
    with Application(store.workspace, provider=DemoProvider()) as group:
        group.rollback(prior)
    assert store.harness().id == prior
    assert len(store.messages("demo-team")) == 2
    assert store.events(report.selected_run_ids[0])


def test_business_validator_rejection_leaves_active_revision_unchanged(store, settings):
    _, plan = prepare(store, settings)
    prior = store.harness().id
    with pytest.raises(ContractError, match="Business validation"):
        apply(store, plan.id, validator=lambda _: False)
    assert store.harness().id == prior
    activated = apply(store, plan.id, validator=lambda harness: isinstance(harness, Harness))
    assert activated.validation == "business"


def test_validator_exception_does_not_activate(store, settings):
    _, plan = prepare(store, settings)

    def fail(_):
        raise RuntimeError("regression check crashed")

    with pytest.raises(RuntimeError):
        apply(store, plan.id, validator=fail)
    assert store.harness().id == plan.parent_revision_id


def test_stale_plan_cannot_replace_a_newer_revision(store, settings):
    report, plan = prepare(store, settings)
    other = propose(store, DemoProvider(), settings, report)
    apply(store, plan.id)
    with pytest.raises(ConflictError, match="Active revision changed"):
        apply(store, other.id)


@pytest.mark.parametrize(
    "path,interface",
    [
        ("../config.toml", "Policy"),
        ("prompts/group.md", "Operation"),
        ("tools/evil.py", "Operation"),
        ("settings.json", "Intervention"),
    ],
)
def test_candidate_rejects_outside_surfaces_and_wrong_interfaces(store, settings, path, interface):
    report, plan = prepare(store, settings)
    plan.changes[0].path = path
    plan.changes[0].interface = interface
    with pytest.raises(ContractError):
        candidate(store, plan, report)


def test_candidate_rejects_unknown_finding_or_task_identifier(store, settings):
    report, plan = prepare(store, settings)
    plan.changes[0].finding_ids = ["fabricated"]
    with pytest.raises(ContractError, match="unknown analysis"):
        candidate(store, plan, report)
    plan.changes[0].finding_ids = [report.findings[0].id]
    plan.changes[0].content += " Use demo-team/001 as the answer."
    with pytest.raises(ContractError, match="verbatim source"):
        candidate(store, plan, report)


@pytest.mark.parametrize(
    "path,interface,content",
    [
        ("representation.json", "Representation", '{"include_metadata":true}'),
        (
            "operations.json",
            "Operation",
            '{"search_mode":"all","search_limit":3,"context_window":1}',
        ),
        (
            "interventions.json",
            "Intervention",
            '{"max_citations":4,"max_answer_chars":1000,"require_citations_for_partial":true}',
        ),
        (
            "prompts/group.md",
            "Policy",
            "Use source records to verify current status and retain uncertainty.",
        ),
    ],
)
def test_all_four_interfaces_compile_into_real_runtime_settings(
    store, settings, path, interface, content
):
    report, plan = prepare(store, settings)
    plan.changes[0].path, plan.changes[0].interface, plan.changes[0].content = (
        path,
        interface,
        content,
    )
    revised = candidate(store, plan, report)
    assert revised.id != plan.parent_revision_id
    assert revised.contents[path] == content


def test_operations_cannot_exceed_fixed_runtime_ceiling(store, settings):
    report, plan = prepare(store, settings)
    plan.changes[0].path = "operations.json"
    plan.changes[0].interface = "Operation"
    plan.changes[0].content = '{"search_limit":10000}'
    with pytest.raises(ValueError):
        candidate(store, plan, report)
