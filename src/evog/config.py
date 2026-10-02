"""Deployment settings are fixed kernel inputs, separate from evolvable files."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import Field, SecretStr

from evog.models import Record


class Settings(Record):
    base_url: str = ""
    model: str = ""
    api_key: SecretStr = SecretStr("")
    max_turns: int = Field(default=16, ge=3, le=80)
    max_tool_calls: int = Field(default=32, ge=1, le=100)
    max_output_tokens: int = Field(default=4096, ge=256, le=32000)
    request_timeout: float = Field(default=90, ge=1, le=600)
    confidence_threshold: float = Field(default=0.5, ge=0, le=1)
    analysis_max_runs: int = Field(default=30, ge=1, le=200)
    analysis_turns: int = Field(default=10, ge=2, le=30)
    max_context_chars: int = Field(default=180000, ge=10000, le=1000000)

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        values = {}
        if path:
            values = tomllib.loads(path.read_text(encoding="utf-8"))
        for field in ("base_url", "model", "api_key"):
            value = os.environ.get(f"EVOG_{field.upper()}")
            if value is not None:
                values[field] = value
        return cls.model_validate(values)
