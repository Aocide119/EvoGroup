# Memory write module (probe)

Probe-only knife. Product prompts under `src/evog/prompts/` stay as they are. Base merge waits
until a live retest accepts the write trigger and the people/events split.

## What changed

Long-term memory writes are a pluggable module under `policy/memory/`, not stacked rules in
`policy/group.md`. The probe harness concatenates that tree into the existing system-prompt
slot `Memory component policy:`.

`policy/group.md` keeps answering rules and points at the Memory write module. Sections 11a–11d
are not restated there.

## People vs events vs group profile

| Surface | Holds | Does not hold |
| --- | --- | --- |
| `people/` | Cross-group abstract portrait: stable role, responsibility boundary, collaboration style, preferences, principles | Dated activity timeline |
| `events/` | Dated decisions and deliveries (the chronicle) | A restated persona |
| `group_profile` | Group-level themes only | One person's deeds, one delivery |

People refs stay few and precise, or say `see events/…`. Dated deeds go to `events/`.

## Assembly

`interaction.assemble_memory_policy` joins, skipping anything absent:

1. `policy/memory/policy.md`
2. `policy/memory/modules/*.md` sorted by filename
3. `policy/memory/rules/*.md` sorted by filename

`write.md` is the FINAL-before checklist: self-check reusable facts, write LTM before FINAL,
soft-route the three surfaces, replace within budget. Sibling modules `profile_budget` and
`write_discipline` stay plug-and-play; drop the files in `modules/` and they assemble in
filename order. No ACL and no hard tool block. No independent promote round (tier-2).

`interaction.system_prompt` places the block after group answering policy. An empty tree omits
the slot. `READ_CONCURRENCY` stays `1` for read columns of the same `scope_id`.

## Acceptance

The experiment bot runs the live 20-episode retest. This repo only checks assembly and the
reporting helpers in `reporting.py`:

- `zero_increment_should_writes`: completed episodes with reusable facts whose LTM snapshot did
  not change. Pass when the count is **0**. Baseline on must-read was **2/20** (`010`, `015`).
- `people_date_density`: mean date mentions per `people/` portrait. Pass when density falls from
  about **4.9** dates/person.
- `ltm_snapshot(root)` is the canonical text `run_probe` should store as `ltm_before` /
  `ltm_after`.
- `probe_report(episodes, portraits)` returns both metrics for the run log.

## Out of scope

- Merging this tree into the product system prompt.
- A second promote pass.
- Parallel reads of the same `scope_id`.
