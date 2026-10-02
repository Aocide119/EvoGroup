# Migration from the AHE-derived research tree

EvoG is a fresh package based on the supplied EvoGroup method. The original AHE-derived checkout
and historical runs remain a separate research archive. No original files are deleted by this
release. AHE's MIT attribution is preserved in `LICENSE` and `NOTICE`.

| Research surface | Release disposition |
| --- | --- |
| Monolithic `evolve.py` orchestration | Replaced by `runtime`, `analysis`, `evolution`, `store` and command orchestration modules |
| `group_bench`, Harbor/E2B, external benchmark adapters | Removed from the release dependency graph |
| Model/topic experiment overlays, fixed question splits, ablations, plotting scripts | Omitted from the product tree |
| NexAU agent debugger bundle, web/shell tools, legacy sandbox glue | Replaced by injectable model transport and read-only trace inspection |
| Per-run copied agent trees and runtime import-path patching | Replaced by typed harness snapshots and fixed operation implementations |
| Five source/navigation tools | Reimplemented with logical paths, explicit group scope, pagination and delivered-reference checks |
| Source memory-unit line lookup | Replaced by canonical message records, stable references and frozen per-run JSONL views |
| `FINAL ANSWER`, `CONFIDENCE`, `ANSWER BIAS` user-facing protocol | Replaced by typed JSON envelopes and normal natural-language CLI output |
| Correctness labels from official question judges | Replaced by optional user/business acceptance feedback; unknown is explicit |
| Progressively disclosed trace diagnosis and bucketed findings | Preserved as product analysis mechanisms with exact field/range evidence validation |
| Unbounded automatic code edits | Bounded declarative Representation/Operation/Policy/Intervention plans |
| Archives, datasets, private `.env`, outputs and model-specific settings | Excluded from release artifacts |

## Data migration

This release does not silently import experimental scores, answer keys, model configurations,
private source data or legacy memory-store notes. Convert original chat exports into the canonical
JSONL contract in `examples/messages.jsonl`; supply the real group ID, source message ID, sender,
timezone-aware timestamp and text. Preserve reply relationships with `reply_to` when available.
Verify converted messages against their original export before importing them.

Legacy runtime layouts are incompatible with the new command workflow. Use `evog` commands
instead of invoking `evolve.py`, experimental YAML overlays, or a debugger subprocess.

## Paper alignment

The method's four stages and five-tool cold start are retained. Low-confidence reflection runs
before external feedback. Informative-experience selection combines subjective confidence with
an optional external signal. Analysis exposes trace ranges on demand, condenses diagnoses and
groups them by inferred query semantics. Revision declares one of four interfaces per logical
change and preserves manifest, parent version and validation information.

The product's feedback, bounded declarative revisions and operator-driven activation are
intentional adaptations. This code does not claim to reproduce the manuscript's experimental
scores, model settings, learned artifacts, full arbitrary-code search space or timed campaigns.
Its demonstrations verify software behavior; deployments need their own quality checks.
