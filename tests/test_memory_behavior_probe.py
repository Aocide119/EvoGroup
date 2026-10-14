from __future__ import annotations

import shutil

from memory_behavior_probe.interaction import (
    GROUP_POLICY,
    MEMORY_SLOT,
    READ_CONCURRENCY,
    assemble_memory_policy,
    system_prompt,
)
from memory_behavior_probe.reporting import (
    ltm_snapshot,
    people_date_density,
    probe_report,
    zero_increment_should_writes,
)


def _write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_assembly_includes_write_module_and_omits_it_when_absent(tmp_path):
    _write(tmp_path, "policy.md", "OVERVIEW")
    _write(tmp_path, "modules/profile_budget.md", "BUDGET")
    _write(tmp_path, "modules/write.md", "WRITE")
    _write(tmp_path, "modules/write_discipline.md", "DISCIPLINE")
    _write(tmp_path, "rules/events.md", "EVENTS")
    _write(tmp_path, "rules/people.md", "PEOPLE")
    _write(tmp_path, "rules/profile.md", "PROFILE")

    assembled = assemble_memory_policy(tmp_path)
    assert assembled.split("\n\n") == [
        "OVERVIEW",
        "BUDGET",
        "WRITE",
        "DISCIPLINE",
        "EVENTS",
        "PEOPLE",
        "PROFILE",
    ]

    (tmp_path / "modules" / "write.md").unlink()
    omitted = assemble_memory_policy(tmp_path)
    assert "WRITE" not in omitted.split("\n\n")
    assert omitted.split("\n\n") == [
        "OVERVIEW",
        "BUDGET",
        "DISCIPLINE",
        "EVENTS",
        "PEOPLE",
        "PROFILE",
    ]

    shutil.rmtree(tmp_path / "modules")
    assert assemble_memory_policy(tmp_path).split("\n\n") == [
        "OVERVIEW",
        "EVENTS",
        "PEOPLE",
        "PROFILE",
    ]
    (tmp_path / "policy.md").unlink()
    shutil.rmtree(tmp_path / "rules")
    assert assemble_memory_policy(tmp_path) == ""


def test_packaged_probe_injects_write_module_into_memory_slot():
    body = assemble_memory_policy()
    assert body.index("# Memory component") < body.index("# Memory write")
    assert body.index("# Memory write") < body.index("# Events")
    assert body.index("# Events") < body.index("# People") < body.index("# Group profile")

    prompt = system_prompt()
    slot = prompt.index(MEMORY_SLOT)
    assert prompt.index("# Group answering") < slot < prompt.index("# Memory write")
    assert "11a" not in GROUP_POLICY.read_text(encoding="utf-8")
    assert "Memory write module" in GROUP_POLICY.read_text(encoding="utf-8")
    assert READ_CONCURRENCY == 1


def test_empty_memory_tree_omits_the_slot(tmp_path):
    prompt = system_prompt(tmp_path)
    assert MEMORY_SLOT not in prompt
    assert prompt.startswith("# Group answering")


def test_product_group_prompt_is_not_the_probe_slot():
    from evog.harness import prompt

    assert MEMORY_SLOT not in prompt("group")
    assert "Memory write module" not in prompt("group")


def test_zero_increment_should_writes_match_must_read_baseline():
    episodes = []
    for index in range(1, 21):
        episode_id = f"{index:03d}"
        unchanged = episode_id in {"010", "015"}
        episodes.append(
            {
                "id": episode_id,
                "status": "completed",
                "reusable_facts": ["stable role"] if unchanged or episode_id == "001" else [],
                "ltm_before": "snapshot-a",
                "ltm_after": "snapshot-a" if unchanged else "snapshot-b",
            }
        )
    episodes.append(
        {
            "id": "099",
            "status": "budget_exhausted",
            "reusable_facts": True,
            "ltm_before": "snapshot-a",
            "ltm_after": "snapshot-a",
        }
    )
    assert zero_increment_should_writes(episodes) == ["010", "015"]
    report = probe_report(episodes, {})
    assert report["zero_increment_should_write_count"] == 2
    assert report["people_date_density"] == 0.0


def test_people_date_density_and_ltm_snapshot(tmp_path):
    stacked = {
        "ada": "2024-01-02 shipped. 2024-02-03 reviewed. 2024-03-04 merged. "
        "2024-04-05 pinged. 2024-05-06 closed.",
        "bao": "Owns release calls. Prefers written decisions. See events/bao.",
    }
    assert people_date_density(stacked) == 2.5
    assert people_date_density({"bao": stacked["bao"]}) == 0.0

    memory = tmp_path / "ltm"
    people = memory / "people"
    people.mkdir(parents=True)
    (people / "ada.md").write_text("Owns the release desk.\n", encoding="utf-8")
    before = ltm_snapshot(memory)
    assert before == "people/ada.md\nOwns the release desk.\n"
    assert ltm_snapshot(tmp_path / "missing") == ""
    (people / "ada.md").write_text("Owns the release desk. Decides in writing.\n", encoding="utf-8")
    assert ltm_snapshot(memory) != before
