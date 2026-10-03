"""The five cold-start tools, with scoped sources and writable navigation notes."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from evog.errors import ContractError
from evog.harness import Harness
from evog.io import atomic_write, dumps, fingerprint, safe_path
from evog.models import Message, Record
from evog.store import Store


class ListArgs(Record):
    path: str = ""
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=50)


class ReadArgs(Record):
    path: str
    start_line: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=50)


class SearchArgs(Record):
    terms: list[str] = Field(min_length=1, max_length=8)
    path: str = "context/"
    offset: int = Field(default=0, ge=0)


class WriteArgs(Record):
    path: str
    content: str = Field(max_length=16000)


ARGUMENTS = {
    "list_files": (
        ListArgs,
        "List authorized context files, scoped notes and reusable skills; use offset for pagination.",
    ),
    "read_file": (
        ReadArgs,
        "Read a bounded range of one-based lines. Continue at next_start_line if truncated. Source lines have stable refs.",
    ),
    "grep_search": (
        SearchArgs,
        "Search message text, sender, timestamp, group/message IDs and reply_to for literal terms, case-insensitively. Visible metadata, notes and skills are searchable too. Continue with next_offset.",
    ),
    "write_file": (
        WriteArgs,
        "Replace a navigation note under memory/. Source context and skills are read-only. Cite original refs in notes.",
    ),
    "create_file": (
        WriteArgs,
        "Create a new navigation note under memory/; fails if it already exists.",
    ),
}


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": args.model_json_schema(),
            },
        }
        for name, (args, description) in ARGUMENTS.items()
    ]


class Tools:
    def __init__(
        self,
        store: Store,
        harness: Harness,
        group_ids: list[str],
        *,
        memory_session: str | None = None,
    ):
        if not group_ids:
            raise ContractError("Explicit group scope is required")
        known = {row["group_id"] for row in store.groups()}
        if not set(group_ids).issubset(known):
            raise ContractError("One or more requested groups have no imported messages")
        self.harness = harness
        # Each source view is frozen at interaction start, even if a later import occurs.
        self.context: dict[str, list[dict[str, Any]]] = {}
        self.group_paths = {}
        for group in sorted(set(group_ids)):
            path = f"context/{fingerprint(group)}.jsonl"
            self.group_paths[path] = group
            self.context[path] = [self._record(message) for message in store.messages(group)]
        self.memory_root = store.workspace / "memory" / fingerprint(sorted(set(group_ids)))
        if memory_session is not None:
            self.memory_root = (
                store.workspace
                / "sessions"
                / fingerprint({"session": memory_session, "groups": sorted(set(group_ids))})
                / "memory"
            )
        safe_path(store.workspace, self.memory_root.relative_to(store.workspace).as_posix())
        self.memory_root.mkdir(parents=True, exist_ok=True)
        self.delivered_refs: set[str] = set()

    def _record(self, message: Message) -> dict[str, Any]:
        row = message.model_dump(mode="json")
        if not self.harness.representation.include_metadata:
            row.pop("metadata")
        row["ref"] = message.ref
        return row

    def files(self) -> list[str]:
        notes = []
        for path in self.memory_root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                relative = path.relative_to(self.memory_root).as_posix()
                safe_path(self.memory_root, relative)
                notes.append("memory/" + relative)
        skills = [name for name in self.harness.contents if name.startswith("skills/")]
        return sorted([*self.context, *notes, *skills])

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in ARGUMENTS:
            raise ContractError("Unknown tool")
        args = ARGUMENTS[name][0].model_validate(arguments)
        return getattr(self, name)(args)

    def list_files(self, args: ListArgs) -> dict[str, Any]:
        names = [name for name in self.files() if name.startswith(args.path)]
        rows = [
            {
                "path": name,
                **({"group_id": self.group_paths[name]} if name in self.group_paths else {}),
            }
            for name in names[args.offset : args.offset + args.limit]
        ]
        next_offset = args.offset + len(rows)
        truncated = next_offset < len(names)
        return {
            "files": rows,
            "total": len(names),
            "truncated": truncated,
            "next_offset": next_offset if truncated else None,
        }

    def _lines(self, path: str) -> list[str]:
        if path in self.context:
            return [dumps(row) for row in self.context[path]]
        if path.startswith("skills/") and path in self.harness.contents:
            return self.harness.contents[path].splitlines()
        if path.startswith("memory/"):
            actual = safe_path(self.memory_root, path.removeprefix("memory/"))
            if actual.stat().st_size > 64000:
                raise ContractError("Note exceeds the read limit")
            return actual.read_text(encoding="utf-8").splitlines()
        raise ContractError("Path is not available in the authorized scope")

    def read_file(self, args: ReadArgs) -> dict[str, Any]:
        source = self._lines(args.path)
        start = args.start_line - 1
        if start >= len(source) and source:
            raise ContractError("start_line exceeds file length")
        selected = []
        size = 0
        for index in range(start, min(start + args.limit, len(source))):
            text = source[index]
            if size + len(text) > 60000:
                break
            row: dict[str, Any] = {"line": index + 1, "text": text}
            if args.path in self.context:
                ref = self.context[args.path][index]["ref"]
                row["ref"] = ref
                self.delivered_refs.add(ref)
            selected.append(row)
            size += len(text)
        if not selected and start < len(source):
            raise ContractError("A line exceeds the per-call read limit")
        end = start + len(selected)
        truncated = end < len(source)
        return {
            "path": args.path,
            "lines": selected,
            "total_lines": len(source),
            "truncated": truncated,
            "next_start_line": end + 1 if truncated else None,
        }

    def grep_search(self, args: SearchArgs) -> dict[str, Any]:
        terms = [term.casefold().strip() for term in args.terms]
        if any(not term or len(term) > 256 for term in terms):
            raise ContractError("Search terms must contain 1–256 characters")
        matches = []
        for path in self.files():
            if not path.startswith(args.path):
                continue
            for index, line in enumerate(self._lines(path)):
                if path in self.context:
                    record = self.context[path][index]
                    fields = [
                        str(record[key]).casefold()
                        for key in ("text", "sender", "timestamp", "group_id", "message_id", "ref")
                    ]
                    if record.get("reply_to") is not None:
                        fields.append(record["reply_to"].casefold())
                    if "metadata" in record:
                        fields.extend(value.casefold() for value in record["metadata"].values())
                else:
                    fields = [line.casefold()]
                hits = [any(term in field for field in fields) for term in terms]
                if all(hits) if self.harness.operations.search_mode == "all" else any(hits):
                    matches.append((path, index, line))
        selected = matches[args.offset : args.offset + self.harness.operations.search_limit]
        rows = []
        returned_refs = set()
        response_chars = 0
        for path, index, line in selected:
            row_refs = set()
            row: dict[str, Any] = {
                "path": path,
                "line": index + 1,
                "excerpt": line[:1400],
                "excerpt_truncated": len(line) > 1400,
            }
            if path in self.context:
                record = self.context[path][index]
                row["ref"] = record["ref"]
                row["group_id"] = record["group_id"]
                # Only complete delivered source records qualify for citations.
                if len(line) <= 1400:
                    row_refs.add(record["ref"])
                window = self.harness.operations.context_window
                if window:
                    neighborhood = self.context[path][max(0, index - window) : index + window + 1]
                    row["context"] = [
                        {
                            "ref": item["ref"],
                            "text": dumps(item)[:1400],
                            "truncated": len(dumps(item)) > 1400,
                        }
                        for item in neighborhood
                    ]
                    row_refs.update(
                        item["ref"] for item in neighborhood if len(dumps(item)) <= 1400
                    )
            size = len(dumps(row))
            if response_chars + size > 60000:
                break
            rows.append(row)
            returned_refs.update(row_refs)
            response_chars += size
        self.delivered_refs.update(returned_refs)
        next_offset = args.offset + len(rows)
        truncated = next_offset < len(matches)
        return {
            "matches": rows,
            "total_matches": len(matches),
            "mode": self.harness.operations.search_mode,
            "truncated": truncated,
            "next_offset": next_offset if truncated else None,
        }

    def _write(self, args: WriteArgs, create: bool) -> dict[str, Any]:
        if not args.path.startswith("memory/"):
            raise ContractError("Only scoped memory/ navigation notes are writable")
        path = safe_path(self.memory_root, args.path.removeprefix("memory/"))
        if path.suffix not in (".md", ".txt", ".json", ".jsonl"):
            raise ContractError("Navigation notes must be text files")
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                stream.write(args.content)
        else:
            atomic_write(path, args.content)
        return {"path": args.path, "written_chars": len(args.content)}

    def write_file(self, args: WriteArgs) -> dict[str, Any]:
        return self._write(args, create=False)

    def create_file(self, args: WriteArgs) -> dict[str, Any]:
        return self._write(args, create=True)
