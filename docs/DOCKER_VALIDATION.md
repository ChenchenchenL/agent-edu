# Docker Validation And Observability

## Purpose

This document describes the default Docker validation path for `agent-edu` and the minimum observability loop used to inspect runtime behavior.

It covers:

- blackbox API validation against a running containerized API
- gated real-provider regression against DashScope-compatible services
- Prometheus, alert rules, and Grafana startup for runtime inspection

## Default Flow

1. Start the core stack:

```bash
make dev-up
```

2. Run in-process API integration tests inside the API image:

```bash
make test-api
```

3. Run Docker blackbox API validation against the running `api` service:

```bash
make docker-api-test
```

4. Start Prometheus and Grafana:

```bash
make observability-up
```

5. If real provider credentials are configured, run the gated real-provider regression:

```bash
make real-provider-regression
```

## Proxy Notes

There are two separate proxy layers:

1. Docker daemon / buildkit proxy
2. container runtime proxy

This repository now passes standard proxy variables into `api` and `tester`
build/runtime environments:

- `HTTP_PROXY`
- `HTTPS_PROXY`
- `ALL_PROXY`
- `NO_PROXY`

### Recommended VMware NAT Default

If the code runs inside a local VMware VM with networking set to `NAT`, prefer
the host `VMnet8` address instead of a changing WLAN address.

Recommended default:

```bash
HTTP_PROXY=http://192.168.127.1:10808
HTTPS_PROXY=http://192.168.127.1:10808
NO_PROXY=localhost,127.0.0.1,postgres,redis,api,prometheus,grafana
```

Why:

- `192.168.127.1` is typically the stable host-side address for VMware `VMnet8`
- it does not change when the host WLAN address changes
- it is a better long-term default than using a transient LAN IP such as `10.x.x.x`

Important:

- the local proxy on the host must allow LAN / VMnet access
- if the proxy only listens on `127.0.0.1`, the VM will not be able to reach it

The `Makefile` now defaults `HTTP_PROXY` and `HTTPS_PROXY` to
`http://192.168.127.1:10808` unless you override them explicitly in your shell.

However, if `docker build` fails while pulling `python:3.11-slim`, the missing
piece is usually the Docker daemon proxy, not the container environment. In
that case you need to configure Docker itself to use your proxy before rerunning
`docker compose up --build`.

## Real Provider Baseline

The current long-run regression baseline is intentionally narrow:

- LLM provider: DashScope-compatible
- Embedding provider: DashScope-compatible
- trigger mode: manual only

The regression suite is disabled unless:

- `AGENT_EDU_API_BASE_URL` is set
- `AGENT_EDU_DATABASE_URL` is set
- `AGENT_EDU_RUN_REAL_PROVIDER_REGRESSION=1`

## Metrics And Dashboards

When `AGENT_EDU_METRICS_ENABLED=1`, the API exposes:

- `GET /metrics`

Prometheus scrapes `api:8000/metrics`.

Prometheus also loads `ops/prometheus/alerts.yml`, which currently contains:

- the long-term memory alert baseline:
  - `MemoryCandidateBacklogHigh`
  - `MemoryMaterializationFailureRateHigh`
  - `MemoryMaintenanceSlow`
  - `MemoryOpenConflictsGrowing`
- the skill health alert baseline:
  - `SkillResolverFailureRateHigh`
  - `SkillNegativeUsageRateHigh`
  - `SkillCuratorPendingBacklogHigh`
  - `SkillCoverageRegressionRecommendationRateHigh`
  - `SkillCuratorJobSlow`

Grafana is provisioned with:

- a default Prometheus datasource
- the `AgentEdu Overview` dashboard

The dashboard includes the long-term memory and skill panels needed for first-pass
operations review:

- memory candidate backlog
- memory governance rate, including promotion / demotion / archive / compression decisions
- memory conflict rate and current open conflicts
- long-term memory materialization failure rate
- memory maintenance p95 duration
- skill usage rate by surface / outcome
- skill resolver failure rate
- skill artifact status counts
- skill curator pending recommendation counts
- skill curator recommendation rate
- skill curator job p95 duration

Default local ports:

- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`

## Recommended Triage Order

When a Docker or real-provider regression fails, inspect in this order:

1. `GET /healthz`
2. `GET /readyz`
3. Grafana request and provider panels
4. `audit_events` for:
   - `llm.chat.completed` / `llm.chat.failed`
   - `llm.quiz.completed` / `llm.quiz.failed`
   - `embedding.query.completed` / `embedding.query.failed`
   - `long_term_memory.materialization.failed`
   - `long_term_memory.extraction.validation_failed`
   - `memory_maintenance.job.retry_scheduled`
   - `memory_maintenance.job.failed`
5. Long-term memory panels and alerts for:
   - candidate backlog
   - promotion / governance decision rate
   - conflict rate and open conflicts
   - materialization failure rate
   - maintenance duration
6. Skill panels and alerts for:
   - usage rate and negative outcome rate
   - resolver failure rate
   - artifact status counts
   - curator pending backlog
   - coverage regression recommendation spikes
   - curator job latency
7. session, message, quiz, skill, and memory tables if persistence behavior looks inconsistent
