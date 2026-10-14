"""Metrics for the memory-behavior probe. The live retest calls these; it is not run here.

Baseline on the must-read set: 2/20 completed episodes left long-term memory unchanged
despite reusable facts (`010`, `015`). People portraits sat near 4.9 dates per person.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

_DATE = re.compile(
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"
    r"|\d{4}年\d{1,2}月(?:\d{1,2}日)?"
    r"|\d{1,2}月\d{1,2}日"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\b",
    re.IGNORECASE,
)


def ltm_snapshot(root: Path) -> str:
    """Canonical file text for an LTM tree. Missing directory is an empty snapshot."""
    if not root.is_dir():
        return ""
    chunks = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rel = path.relative_to(root).as_posix()
        chunks.append(f"{rel}\n{path.read_text(encoding='utf-8')}")
    return "\n---\n".join(chunks)


def people_date_counts(portraits: Mapping[str, str]) -> dict[str, int]:
    return {name: len(_DATE.findall(text)) for name, text in portraits.items()}


def people_date_density(portraits: Mapping[str, str]) -> float:
    if not portraits:
        return 0.0
    counts = people_date_counts(portraits)
    return sum(counts.values()) / len(counts)


def zero_increment_should_writes(episodes: Sequence[Mapping]) -> list[str]:
    """Completed episodes that had reusable facts but left LTM content unchanged."""
    missed: list[str] = []
    for episode in episodes:
        if episode.get("status") != "completed":
            continue
        if not episode.get("reusable_facts"):
            continue
        if episode.get("ltm_before") == episode.get("ltm_after"):
            missed.append(str(episode["id"]))
    return missed


def probe_report(episodes: Sequence[Mapping], portraits: Mapping[str, str]) -> dict:
    missed = zero_increment_should_writes(episodes)
    return {
        "zero_increment_should_writes": missed,
        "zero_increment_should_write_count": len(missed),
        "people_date_density": people_date_density(portraits),
        "people_date_counts": people_date_counts(portraits),
    }
