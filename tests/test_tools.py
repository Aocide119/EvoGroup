import json

import pytest

from evog.demo import DEMO_MESSAGES
from evog.errors import ContractError
from evog.harness import Harness
from evog.io import dumps, fingerprint
from evog.models import Message
from evog.tools import Tools, tool_definitions


def tools_for(store, groups=None, **patches):
    contents = store.harness().contents
    contents.update(patches)
    return Tools(store, Harness(contents), groups or ["demo-team"])


def test_five_tools_and_scoped_read_view(store):
    store.ingest(iter([Message.model_validate({**DEMO_MESSAGES[0], "group_id": "private"})]))
    tools = tools_for(store)
    assert len(tool_definitions()) == 5
    files = tools.execute("list_files", {})["files"]
    assert len(files) == 1
    assert files[0]["group_id"] == "demo-team"
    result = tools.execute("read_file", {"path": files[0]["path"], "limit": 1})
    assert result["truncated"] and result["next_start_line"] == 2
    assert tools.delivered_refs == {"demo-team/001"}
    with pytest.raises(ContractError):
        Tools(store, store.harness(), [])
    with pytest.raises(ContractError):
        Tools(store, store.harness(), ["unknown"])


def test_source_view_is_frozen_at_run_start(store):
    tools = tools_for(store)
    store.ingest(iter([Message.model_validate({**DEMO_MESSAGES[0], "message_id": "003"})]))
    assert tools.execute("grep_search", {"terms": ["release"]})["total_matches"] == 2


@pytest.mark.parametrize(
    "path", ["context/source.jsonl", "../secret.md", "memory/../../secret.md", "/tmp/secret.md"]
)
def test_write_cannot_escape_notes(store, path):
    with pytest.raises(ContractError):
        tools_for(store).execute("write_file", {"path": path, "content": "no"})


def test_create_exclusive_write_replace_and_scope_isolation(store):
    tools = tools_for(store)
    tools.execute("create_file", {"path": "memory/notes.md", "content": "first"})
    with pytest.raises(FileExistsError):
        tools.execute("create_file", {"path": "memory/notes.md", "content": "second"})
    tools.execute("write_file", {"path": "memory/notes.md", "content": "updated"})
    assert tools.execute("read_file", {"path": "memory/notes.md"})["lines"][0]["text"] == "updated"
    store.ingest(iter([Message.model_validate({**DEMO_MESSAGES[0], "group_id": "another"})]))
    other = tools_for(store, ["demo-team", "another"])
    assert "memory/notes.md" not in other.files()


def test_question_session_notes_remain_bound_to_the_authorized_groups(store):
    first = Tools(store, store.harness(), ["demo-team"], memory_session="same-session")
    first.execute("create_file", {"path": "memory/note.md", "content": "navigation"})
    second = Tools(store, store.harness(), ["demo-team"], memory_session="another-question")
    assert "memory/note.md" not in second.files()
    store.ingest(iter([Message.model_validate({**DEMO_MESSAGES[0], "group_id": "another"})]))
    wider = Tools(store, store.harness(), ["demo-team", "another"], memory_session="same-session")
    assert "memory/note.md" not in wider.files()


def test_note_symlink_escape(store, tmp_path):
    tools = tools_for(store)
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    try:
        (tools.memory_root / "escape.md").symlink_to(outside)
    except OSError:
        pytest.skip("Symlinks unavailable")
    with pytest.raises(ContractError):
        tools.execute("read_file", {"path": "memory/escape.md"})


def test_search_is_literal_and_paginated_and_operation_is_effective(store):
    tools = tools_for(
        store, **{"operations.json": '{"search_mode":"any","search_limit":1,"context_window":0}'}
    )
    first = tools.execute("grep_search", {"terms": ["release"]})
    assert first["truncated"] and first["next_offset"] == 1
    assert (
        tools.execute("grep_search", {"terms": ["release"], "offset": 1})["matches"][0]["ref"]
        == "demo-team/002"
    )
    assert tools.execute("grep_search", {"terms": [".*"]})["total_matches"] == 0
    contents = {"operations.json": '{"search_mode":"all","search_limit":8,"context_window":1}'}
    conjunctive = tools_for(store, **contents)
    result = conjunctive.execute("grep_search", {"terms": ["release", "changed"]})
    assert result["total_matches"] == 1
    assert len(result["matches"][0]["context"]) == 2


def test_truncated_source_excerpt_does_not_validate_citation(store):
    store.ingest(
        iter(
            [
                Message.model_validate(
                    {**DEMO_MESSAGES[0], "message_id": "long", "text": "release " + "x" * 3000}
                )
            ]
        )
    )
    tools = tools_for(store)
    result = tools.execute("grep_search", {"terms": ["xxx"]})
    assert result["matches"][0]["excerpt_truncated"]
    assert "demo-team/long" not in tools.delivered_refs
    match = result["matches"][0]
    tools.execute("read_file", {"path": match["path"], "start_line": match["line"], "limit": 1})
    assert "demo-team/long" in tools.delivered_refs


def test_representation_controls_metadata(store):
    store.ingest(
        iter(
            [
                Message.model_validate(
                    {**DEMO_MESSAGES[0], "message_id": "meta", "metadata": {"topic": "launch"}}
                )
            ]
        )
    )
    default = tools_for(store)
    path = next(iter(default.context))
    assert all("metadata" not in row for row in default.context[path])
    expanded = tools_for(store, **{"representation.json": '{"include_metadata":true}'})
    assert any(row.get("metadata", {}).get("topic") == "launch" for row in expanded.context[path])


def test_unknown_tool_arguments_rejected(store):
    with pytest.raises(ValueError):
        tools_for(store).execute("grep_search", {"terms": ["release"], "shell": "rm"})


def test_source_lines_have_stable_refs(store):
    tools = tools_for(store)
    path = next(iter(tools.context))
    result = tools.execute("read_file", {"path": path})
    assert json.loads(result["lines"][1]["text"])["reply_to"] == "001"


@pytest.mark.parametrize(
    "term,refs",
    [
        ("MAYA", {"demo-team/001"}),
        ("2026-01-06", {"demo-team/002"}),
        ("+08:00", {"demo-team/001", "demo-team/002"}),
        ("demo-team", {"demo-team/001", "demo-team/002"}),
        ("002", {"demo-team/002"}),
        ("001", {"demo-team/001", "demo-team/002"}),
    ],
)
def test_search_finds_attribution_local_date_and_message_links(store, term, refs):
    result = tools_for(store).execute("grep_search", {"terms": [term]})
    assert {match["ref"] for match in result["matches"]} == refs


def test_search_conjunction_combines_sender_date_and_body(store):
    tools = tools_for(store, **{"operations.json": '{"search_mode":"all"}'})
    result = tools.execute("grep_search", {"terms": ["Noah", "2026-01-06", "changed"]})
    assert [match["ref"] for match in result["matches"]] == ["demo-team/002"]
    assert tools.execute("grep_search", {"terms": ["sender"]})["total_matches"] == 0


def test_scoped_memory_root_symlink_escape_is_rejected(store, tmp_path):
    memory = store.workspace / "memory"
    memory.mkdir(exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (memory / fingerprint(["demo-team"])).symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks unavailable")
    with pytest.raises(ContractError, match="escapes"):
        tools_for(store)


def test_long_search_windows_are_paginated_before_delivery_validation(store):
    messages = [
        Message.model_validate(
            {**DEMO_MESSAGES[0], "message_id": f"large-{index:02d}", "text": "release " + "x" * 700}
        )
        for index in range(40)
    ]
    store.ingest(iter(messages))
    tools = tools_for(
        store, **{"operations.json": '{"search_mode":"any","search_limit":30,"context_window":5}'}
    )
    result = tools.execute("grep_search", {"terms": ["release"]})
    assert len(dumps(result)) < 61000
    assert result["truncated"]
    actually_delivered = {match["ref"] for match in result["matches"]}
    actually_delivered.update(
        item["ref"] for match in result["matches"] for item in match["context"]
    )
    assert tools.delivered_refs.issubset(actually_delivered)
    assert result["next_offset"] == len(result["matches"])
