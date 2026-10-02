# Release validation — 0.1.0

Validated on October 3, 2026, on macOS. This records software checks for the reconstructed
command-line framework; it does not report model quality or reproduce paper experiments.

| Check | Observed result |
| --- | --- |
| Python 3.13.11 | 93 tests passed |
| Python 3.11.15 | 93 tests passed |
| Ruff lint and formatting | Passed |
| CLI offline demo | Complete experience/revision loop completed |
| Wheel installed in a clean Python 3.11 environment | CLI offline demo completed using packaged prompt resources |
| Wheel and source distribution | Built successfully; all five role prompts included |
| Archive contents | No private workspaces, credentials, experimental archives, virtual environments or bytecode |
| Credential-shaped string scan | No provider-token or GitHub-token patterns found in release source |
| Runtime and prompt legacy-term scan | No research backends, scoring targets or legacy answer markers in runtime source |

The regression suite checks atomic/idempotent ingestion, source conflicts, timezone handling,
explicit group scope, note isolation, traversal and symlink escapes, pagination and truncated
evidence, delivered-citation validation, reflection failures, budget boundaries, feedback cells,
unfinished/incident/contract-failure separation, timezone preservation and UTC ordering,
metadata-aware search, progressive trace ranges, forged evidence, four revision surfaces,
stale plans, business-validator failure, rollback and safe provider failures.

Live model endpoints and business-level answer quality have not been tested in this validation.
The committed CI matrix specifies Python 3.11–3.13 on Ubuntu and Windows; those hosted CI jobs
have not been run by this local validation. Generated revisions have structural validation unless
an integrating application supplies and passes a business validator. Arbitrary Python code
evolution remains outside this release's declarative revision surfaces.
