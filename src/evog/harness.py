"""Four bounded revision surfaces, compiled by the fixed runtime."""

from __future__ import annotations

import json
import re
from importlib.resources import files

from pydantic import Field

from evog.errors import ContractError
from evog.io import dumps, fingerprint
from evog.models import Record


def prompt(name: str) -> str:
    return files("evog").joinpath(f"prompts/{name}.md").read_text(encoding="utf-8")


class Representation(Record):
    include_metadata: bool = False


class Operations(Record):
    search_mode: str = Field(default="any", pattern=r"^(any|all)$")
    search_limit: int = Field(default=8, ge=1, le=30)
    context_window: int = Field(default=0, ge=0, le=5)


class Interventions(Record):
    require_citations_for_partial: bool = True
    max_citations: int = Field(default=32, ge=1, le=64)
    max_answer_chars: int = Field(default=8000, ge=256, le=12000)


FILE_INTERFACES = {
    "representation.json": "Representation",
    "operations.json": "Operation",
    "interventions.json": "Intervention",
    "prompts/group.md": "Policy",
}


def interface_for(path: str) -> str:
    if path in FILE_INTERFACES:
        return FILE_INTERFACES[path]
    if re.fullmatch(r"skills/[a-z0-9][a-z0-9_-]{0,63}\.md", path):
        return "Policy"
    raise ContractError(f"File is outside revision surfaces: {path}")


def initial_files() -> dict[str, str]:
    return {
        "prompts/group.md": prompt("group"),
        "representation.json": dumps(Representation().model_dump()),
        "operations.json": dumps(Operations().model_dump()),
        "interventions.json": dumps(Interventions().model_dump()),
    }


class Harness:
    def __init__(self, contents: dict[str, str]):
        if not set(FILE_INTERFACES).issubset(contents):
            raise ContractError("Harness is missing required files")
        if len(contents) > 36 or sum(len(text) for text in contents.values()) > 160000:
            raise ContractError("Harness exceeds the bounded file budget")
        for path, text in contents.items():
            interface_for(path)
            if not text.strip() or len(text) > 40000:
                raise ContractError(f"Empty or oversized harness file: {path}")
        self.contents = dict(contents)
        self.representation = Representation.model_validate(
            json.loads(contents["representation.json"])
        )
        self.operations = Operations.model_validate(json.loads(contents["operations.json"]))
        self.interventions = Interventions.model_validate(
            json.loads(contents["interventions.json"])
        )
        self.id = fingerprint(contents)

    @property
    def system_prompt(self) -> str:
        return self.contents["prompts/group.md"]
