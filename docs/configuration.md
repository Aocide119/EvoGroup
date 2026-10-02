# Deployment configuration

Optional TOML settings:

```toml
base_url = "https://your-provider.example/v1"
model = "your-model"
max_turns = 16
max_tool_calls = 32
max_output_tokens = 4096
request_timeout = 90
confidence_threshold = 0.5
analysis_max_runs = 30
analysis_turns = 10
max_context_chars = 180000
```

Use `evog --config settings.toml ask '...' --group product`. Provide credentials via
`EVOG_API_KEY`; use `EVOG_BASE_URL` and `EVOG_MODEL` to override the corresponding TOML fields.
Keys are represented as secrets in runtime configuration and excluded from persisted settings. Do not put
real keys into configuration committed to Git. Unknown configuration fields are rejected.

`max_turns` counts interaction model calls; low-confidence reflection gets at most one separate
call. The last interaction turn requests a final answer with no tools. Tool calls have their
own cap. Model messages use a bounded character budget as a portable approximation, not a token
count. Provider failure, tool execution failure, output-contract failure and budget exhaustion
are recorded as separate run statuses; only output-contract and budget failures are eligible for
trace diagnosis. Provider usage is observed telemetry, not billing.

Each analysis has a bounded number of selected runs. Each diagnosis has its own model-turn cap;
synthesis and proposal each make one additional model request. HTTP 429 and selected server
errors receive up to two bounded retries; transport errors fail promptly. A request timeout is
per HTTP request, rather than a whole multi-stage wall-clock deadline.

Deployment settings are fixed inputs. The four evolvable files are JSON configuration objects
and the group prompt; see `evog.harness` for their schemas. Workspace location defaults to `.evog`
and must not be shared between unrelated tenants without deployment-level access control.
