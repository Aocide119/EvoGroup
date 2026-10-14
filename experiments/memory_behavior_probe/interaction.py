"""Probe harness wiring for the Memory component policy slot.

Product interaction does not import this module. Missing policy files are skipped so a
probe can drop modules in or out without a code change.
"""

from __future__ import annotations

from pathlib import Path

MEMORY_SLOT = "Memory component policy:"
# Same scope_id read columns stay serial. An independent promote round is tier-2.
READ_CONCURRENCY = 1

PROBE_ROOT = Path(__file__).resolve().parent
POLICY_ROOT = PROBE_ROOT / "policy"
MEMORY_ROOT = POLICY_ROOT / "memory"
GROUP_POLICY = POLICY_ROOT / "group.md"


def assemble_memory_policy(root: Path | None = None) -> str:
    """Concatenate policy.md, then modules/*.md, then rules/*.md. Each glob is sorted."""
    root = MEMORY_ROOT if root is None else root
    parts: list[str] = []
    overview = root / "policy.md"
    if overview.is_file():
        parts.append(overview.read_text(encoding="utf-8"))
    for folder in ("modules", "rules"):
        directory = root / folder
        if not directory.is_dir():
            continue
        parts.extend(path.read_text(encoding="utf-8") for path in sorted(directory.glob("*.md")))
    return "\n\n".join(part.strip() for part in parts if part.strip())


def memory_policy_block(root: Path | None = None) -> str:
    body = assemble_memory_policy(root)
    if not body:
        return ""
    return f"{MEMORY_SLOT}\n{body}\n"


def system_prompt(root: Path | None = None, group_path: Path | None = None) -> str:
    group = (GROUP_POLICY if group_path is None else group_path).read_text(encoding="utf-8").strip()
    block = memory_policy_block(root)
    if not block:
        return group + "\n"
    return f"{group}\n\n{block}"
