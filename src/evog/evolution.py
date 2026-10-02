"""Evidence-linked plans, bounded candidates, atomic activation, and rollback."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from evog.config import Settings
from evog.errors import ContractError
from evog.harness import (
    FILE_INTERFACES,
    Harness,
    Interventions,
    Operations,
    Representation,
    interface_for,
    prompt,
)
from evog.io import dumps
from evog.models import AnalysisReport, AppliedRevision, EvolutionPlan, PlanDraft
from evog.providers import Provider
from evog.store import Store

Validator = Callable[[Harness], bool]


def candidate(store: Store, plan: EvolutionPlan, report: AnalysisReport) -> Harness:
    if plan.analysis_id != report.id or plan.parent_revision_id != report.revision_id:
        raise ContractError("Plan is not linked to its source analysis and revision")
    parent = store.harness(plan.parent_revision_id)
    contents = dict(parent.contents)
    findings = {finding.id for finding in report.findings}
    seen = set()
    protected = {run_id for run_id in [*report.selected_run_ids, *report.control_run_ids]}
    for group in store.groups():
        for message in store.messages(group["group_id"]):
            protected.add(message.ref)
            if len(message.text) >= 40:
                protected.add(message.text)
    for change in plan.changes:
        if change.path in seen:
            raise ContractError("A plan must replace each file at most once")
        seen.add(change.path)
        if interface_for(change.path) != change.interface:
            raise ContractError("Change interface does not match the declared file's role")
        if not set(change.finding_ids).issubset(findings):
            raise ContractError("Change refers to an unknown analysis finding")
        if not all(
            value.strip()
            for value in (
                change.rationale,
                change.expected_effect,
                change.regression_risk,
                change.validation,
            )
        ):
            raise ContractError(
                "Changes require rationale, expected effect, regression risk and validation"
            )
        if any(value in change.content for value in protected):
            raise ContractError(
                "Reusable harness content includes an interaction ID or verbatim source"
            )
        contents[change.path] = change.content
    return Harness(contents)


def propose(
    store: Store, provider: Provider | None, settings: Settings, report: AnalysisReport
) -> EvolutionPlan:
    if store.harness().id != report.revision_id:
        raise ContractError("Analyze the active revision before proposing changes")
    if not report.findings:
        draft = PlanDraft(summary="No inspected finding supports a harness revision", changes=[])
    else:
        if provider is None:
            raise ContractError("A model provider is required for revision proposals")
        supplied: dict[str, Any] = {
            "harness": store.harness().contents,
            "findings": [finding.model_dump() for finding in report.findings],
            "coverage": report.coverage,
            "incomplete": report.incomplete,
            "history": store.revisions(),
            "permitted_files": FILE_INTERFACES,
            "new_skill_paths": "skills/<lowercase-name>.md",
            "configuration_schemas": {
                "representation.json": Representation.model_json_schema(),
                "operations.json": Operations.model_json_schema(),
                "interventions.json": Interventions.model_json_schema(),
            },
        }
        if len(dumps(supplied)) > settings.max_context_chars:
            raise ContractError("Revision proposal context budget exhausted")
        reply = provider.complete(
            [
                {
                    "role": "system",
                    "content": prompt("evolve")
                    + "\nSchema: "
                    + dumps(PlanDraft.model_json_schema()),
                },
                {"role": "user", "content": dumps(supplied)},
            ],
            [],
        )
        draft = PlanDraft.model_validate_json(reply.content)
    plan = EvolutionPlan(
        **draft.model_dump(),
        id=uuid4().hex,
        analysis_id=report.id,
        parent_revision_id=report.revision_id,
    )
    revised = candidate(store, plan, report)
    if plan.changes and revised.id == plan.parent_revision_id:
        plan = plan.model_copy(
            update={
                "changes": [],
                "summary": "Proposed behavior is already present in the active harness",
            }
        )
    store.save_artifact(plan.id, "plan", plan.model_dump(mode="json"))
    return plan


def apply(store: Store, plan_id: str, validator: Validator | None = None) -> AppliedRevision:
    plan = EvolutionPlan.model_validate(store.artifact(plan_id, "plan"))
    report = AnalysisReport.model_validate(store.artifact(plan.analysis_id, "analysis"))
    if not plan.changes:
        raise ContractError("Plan has no changes to activate")
    next_harness = candidate(store, plan, report)
    if next_harness.id == plan.parent_revision_id:
        raise ContractError("Plan does not change the harness")
    validation = "structural"
    if validator is not None:
        if validator(next_harness) is not True:
            raise ContractError(
                "Business validation rejected the candidate; active revision is unchanged"
            )
        validation = "business"
    store.activate(next_harness, plan.parent_revision_id, plan.id, validation)
    return AppliedRevision(
        revision_id=next_harness.id,
        parent_revision_id=plan.parent_revision_id,
        plan_id=plan.id,
        validation=validation,
    )
