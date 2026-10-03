# Release validation: 0.1.0

Local validation on October 3, 2026, on macOS.

## Software checks

| Check | Observed result |
| --- | --- |
| Python 3.11.15 | 110 tests passed |
| Ruff lint and formatting | Passed |
| CLI offline demo | Complete experience/revision loop completed |
| Wheel installed in a clean Python 3.11 environment | CLI offline demo completed using packaged prompt resources |
| Wheel and source distribution | Built successfully; all five role prompts included |
| Archive contents | No private workspaces, credentials, experimental archives, virtual environments or bytecode |
| Credential-shaped string scan | No provider-token or GitHub-token patterns found in release source |

The regression suite checks atomic/idempotent ingestion, source conflicts, timezone handling,
explicit group scope, note isolation, traversal and symlink escapes, pagination and truncated
evidence, delivered-citation validation, reflection failures, budget boundaries, feedback cells,
unfinished/incident/contract-failure separation, timezone preservation and UTC ordering,
metadata-aware search, progressive trace ranges, forged evidence, four revision surfaces,
stale plans, business-validator failure, rollback and safe provider failures. Benchmark checks
cover corpus conversion, answer-key isolation, episode selection, official verdict parsing,
judge failures, paired transitions and candidate activation.

## Live benchmark smoke tests

Small samples were evaluated with `gpt-5.5` through a Chat Completions-compatible endpoint.

| Sample | Passed | Failed | Unscored | Evolution outcome |
| --- | ---: | ---: | ---: | --- |
| EverMemBench, 4 questions | 2 | 2 | 0 | Analysis evidence validation incomplete |
| GroupMemBench Finance, 6 question types | 2 | 3 | 1 | Analysis evidence validation incomplete |
| EverMemBench, 1 question | 0 | 1 | 0 | Analysis completed with one finding; no supported revision |

The unscored GroupMemBench question exhausted its interaction budget. These runs exercised
dataset import, tool use, scoring and trace analysis. Live candidate activation has not been
demonstrated; the offline regression suite covers that path. Full-dataset evaluation remains
pending, and these small samples do not estimate benchmark performance.

The CI matrix targets Python 3.11–3.13 on Ubuntu and Windows. Hosted CI has not been run during
local validation. Application quality requires representative deployment checks; arbitrary
Python code evolution is outside the declarative revision surfaces.
