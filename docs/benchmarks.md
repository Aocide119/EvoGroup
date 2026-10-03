# Benchmark evaluation

EvoG evaluates group-context answering on EverMemBench and GroupMemBench. The CLI supports
baseline runs and evolution cycles with official scoring, isolated memory sessions and paired
candidate validation.

## Data and isolation

The readers support the checked out layouts below.

| Benchmark | Source corpus | Questions | Question kinds |
| --- | --- | ---: | --- |
| EverMemBench | `dataset/<topic>/dialogue.json` + `qa_<topic>.json` | 2,400 | single hop, multi hop, temporal, constraint, proactivity, update, style, skill, role |
| GroupMemBench | `data/final/<Domain>/*.json` + `questions/<Domain>/*.jsonl` | 745 | multi hop, knowledge update, temporal, implicit user, term ambiguity, abstention |

Gold answers, evidence coordinates and judge output stay in the benchmark runner.
The answer prompt receives the question, an optional asking-user identity and answer options. Every
question gets a fresh memory session, so navigation notes cannot leak between questions or from a
multi-group run into a single-group run.

The source conversion retains speaker, timestamp, reply links and benchmark metadata. EverMemBench
keeps its dated/group/message layout; GroupMemBench keeps channel, role, phase and decision fields.
Naive timestamps use `--timezone` (default `UTC`); original offsets are retained when present.

## Commands

List a deterministic sample without calling a model:

```bash
uv run evog --workspace .evog --config benchmark.toml benchmark list evermembench \
  --data-root /path/to/EverMemBench --topic 01 --question-type F_MH --limit 2
```

Run a baseline sample with an OpenAI-compatible endpoint:

```bash
export EVOG_API_KEY='…'
uv run evog --workspace .evog --config examples/benchmark.toml benchmark run evermembench \
  --data-root /path/to/EverMemBench --topic 01 --limit 4 \
  --episode-file splits/evermem-smoke.txt --output results/evermem-baseline.json
```

Run the full product loop. `cycle` performs baseline interaction, official benchmark scoring,
confidence/feedback selection, APD diagnosis, finding synthesis, revision proposal, candidate
validation and paired candidate evaluation. A candidate is activated only when its validation
sample has no pass-to-fail transition and no unscored result.

```bash
uv run evog --workspace .evog --config benchmark.toml benchmark cycle groupmembench \
  --data-root /path/to/GroupMemBench-main --domain Finance \
  --question-type multi_hop --limit 2 \
  --validation-episode-file splits/groupmem-heldout.txt \
  --output results/groupmem-cycle.json
```

Use `--all` only after a smoke run. The 2,400 EverMemBench questions and 745 GroupMemBench
questions are model- and budget-intensive. Pass an episode-ID file with `--episode-file`, using
one ID per line; blank lines and lines starting with `#` are ignored. IDs are checked before
limiting so a typo cannot silently select a different set.

## Judge protocols

EverMemBench multiple-choice answers are normalized to option letters and scored locally.
Other EverMemBench rows use its official `CORRECT`/`WRONG` JSON judge prompt. GroupMemBench
uses the official `Final: Correct` / `Final: Incorrect` parser and prompt. A judge transport failure
or unparseable reply is recorded as `passed: null`, never as a wrong answer.

Judge prompts follow EverMemBench's `eval/config/prompts.yaml` and GroupMemBench's
`prompts/hipporag_judge_system.txt`.

Each result JSON contains the exact corpus fingerprint, model name, baseline/candidate traces,
token usage, tool-call count, per-question status, judge response and paired transition counts.
API keys are read from `EVOG_API_KEY` and are never persisted in the result or trace.
