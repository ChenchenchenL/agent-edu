# Local Development Runbook

This is the single source of truth for starting, verifying, and troubleshooting the Agent-Edu development environment.

## Table of Contents

1. [Recommended Development Mode](#recommended-development-mode)
2. [Quick Start](#quick-start)
3. [Development Modes](#development-modes)
4. [Environment Variables](#environment-variables)
5. [Verification & Smoke Tests](#verification--smoke-tests)
6. [Troubleshooting](#troubleshooting)
7. [Common Issues](#common-issues)

---

## Recommended Development Mode

**Current recommended mode: `backend-docker + frontend-local`**

- Backend (API, worker, PostgreSQL, Redis) runs in Docker
- Frontend runs as a local Vite dev server
- Vite proxies `/api/*` requests to the Docker backend

This is the most stable and least disruptive path. It requires minimal configuration and matches the current repository structure.

---

## Quick Start

### 1. Clone and Configure

```bash
git clone <repository-url>
cd agent-edu
cp .env.example .env
# Edit .env if needed (defaults work for most cases)
```

### 2. Start Backend Stack

```bash
make dev-up
```

This starts:
- `api` - FastAPI application (port 8000)
- `worker` - Background job processor
- `postgres` - PostgreSQL database with pgvector
- `redis` - Redis for job queue and caching

The API automatically runs database migrations on startup.

Wait for the API to become healthy (typically 10-30 seconds). Verify with:

```bash
curl http://localhost:8000/healthz
# Expected: {"status":"ok"}

curl http://localhost:8000/readyz
# Expected: {"status":"ok","checks":{...}}
```

### 3. Start Frontend (Separate Terminal)

```bash
cd packages/frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

### 4. Verify Integration

1. Frontend loads without infinite spinner
2. Goals page displays (may show empty state if no data)
3. Create a learning goal
4. Open a session and send a message
5. Verify response appears

### 5. Stop Environment

```bash
# Stop frontend (Ctrl+C in frontend terminal)

# Stop backend stack
make dev-down
```

---

## Development Modes

### Mode A: Backend-Docker + Frontend-Local (Recommended)

**Use when:** Standard development, testing frontend integration

**Setup:**
```bash
# Terminal 1: Backend
make dev-up

# Terminal 2: Frontend
cd packages/frontend
npm run dev
```

**Access:**
- Frontend: http://localhost:5173
- API: http://localhost:8000
- API Docs: http://localhost:8000/docs

**Pros:**
- Matches production-like backend environment
- Frontend hot reload works
- Minimal configuration

**Cons:**
- Backend changes require `docker compose restart api` or `make dev-down && make dev-up`
- Worker changes require full restart

### Mode B: Local Backend + Local Frontend

**Use when:** Rapid backend iteration, debugging backend logic

**Setup:**
```bash
# Terminal 1: Infrastructure only
docker compose up -d postgres redis

# Terminal 2: Backend (local)
make install-local
alembic upgrade head
uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 3: Worker (local)
python -m apps.worker.main

# Terminal 4: Frontend
cd packages/frontend
npm run dev
```

**Pros:**
- Backend hot reload with `--reload`
- Fastest feedback loop for backend changes

**Cons:**
- Requires local Python environment
- More complex setup
- Must manage multiple processes manually

### Mode C: Full-Stack Docker (Future Enhancement)

**Status:** Not currently implemented

This would add a `frontend` service to the Docker Compose stack. Not recommended for development due to slower feedback loops.

---

## Environment Variables

### Backend Configuration

Copy `.env.example` to `.env` and adjust as needed:

**Required (defaults work for most cases):**
```bash
AGENT_EDU_APP_ENV=development
AGENT_EDU_API_PORT=8000
AGENT_EDU_DATABASE_URL=postgresql+asyncpg://agent_edu:agent_edu@postgres:5432/agent_edu
AGENT_EDU_REDIS_URL=redis://redis:6379/0
```

**LLM Provider:**
```bash
# Mock provider (default, no API key needed)
AGENT_EDU_LLM_PROVIDER=mock
AGENT_EDU_LLM_MODEL=mock-tutor-v1

# Real provider example (DashScope)
# AGENT_EDU_LLM_PROVIDER=dashscope_compatible
# AGENT_EDU_LLM_MODEL=qwen3.5-flash
# AGENT_EDU_LLM_BASE_URL=https://your-endpoint/v1
# AGENT_EDU_LLM_API_KEY=your-api-key
```

**Feature Flags:**
```bash
AGENT_EDU_ALLOWED_SKILLS=explain_concept,create_quiz,adaptive_hint,plan_study_path,schedule_review
AGENT_EDU_METRICS_ENABLED=1
```

### Frontend Configuration

Frontend environment variables are optional. Defaults work for the recommended development mode.

**Optional overrides:**
```bash
# Override API proxy target (only if backend runs on different port/host)
VITE_API_PROXY_TARGET=http://localhost:8000

# Override API base URL (only for non-standard setups)
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

Create a `.env` file in `packages/frontend/` if you need to override defaults:

```bash
cd packages/frontend
cat > .env <<EOF
VITE_API_PROXY_TARGET=http://localhost:8000
EOF
```

---

## Verification & Smoke Tests

### Backend Health Checks

```bash
# Basic health check
curl http://localhost:8000/healthz
# Expected: {"status":"ok"}

# Readiness check (includes dependency verification)
curl http://localhost:8000/readyz
# Expected: {"status":"ok","checks":{"database":"ok","redis":"ok"}}

# Metrics endpoint (if AGENT_EDU_METRICS_ENABLED=1)
curl http://localhost:8000/metrics
```

### Backend Smoke Tests

```bash
# Run API integration tests
make test-api

# Run Docker blackbox tests
make docker-api-test

# Run all unit tests
make test
```

### Frontend Integration Smoke

Manual verification checklist:

1. **Page Loads**
   - [ ] Frontend loads at http://localhost:5173
   - [ ] No infinite spinner
   - [ ] No console errors about API connectivity

2. **Goals Page**
   - [ ] `/goals` route loads
   - [ ] Can view existing goals or empty state
   - [ ] Can create a new goal

3. **Sessions Page**
   - [ ] `/sessions` route loads
   - [ ] Can create a new session
   - [ ] Session appears in list

4. **Learning Workspace**
   - [ ] Can open a session
   - [ ] Can send a message
   - [ ] Receives a response (may take a few seconds)
   - [ ] No timeout errors

5. **Operator Dashboard**
   - [ ] `/operator` route loads
   - [ ] Displays metrics and audit events

### Automated Stack Smoke

```bash
# Verify backend services are running
make ps

# Check API and worker logs
make logs-api
make logs-worker

# Quick API smoke test
make smoke-api
```

---

## Troubleshooting

### Fixed Triage Order

When encountering issues, follow this exact order. Do not skip steps.

#### 1. Process Layer

**Check Docker services:**
```bash
make ps
# or
docker compose ps
```

Expected output:
- `api` - running (healthy)
- `worker` - running
- `postgres` - running (healthy)
- `redis` - running (healthy)

**Check frontend dev server:**
- Is `npm run dev` running in the frontend directory?
- Does the terminal show "Local: http://localhost:5173"?
- Are there any errors in the frontend terminal?

#### 2. Backend Health Layer

**Test API health:**
```bash
curl http://localhost:8000/healthz
```

If this fails:
- API is not running or not yet ready
- Check API logs: `make logs-api`
- Wait 30 seconds and retry

**Test API readiness:**
```bash
curl http://localhost:8000/readyz
```

If healthz passes but readyz fails:
- Database or Redis is not ready
- Check logs: `docker compose logs postgres redis`
- Migration may have failed: check API logs for "alembic" errors

#### 3. Log Layer

**API logs:**
```bash
make logs-api
# or
docker compose logs -f api
```

Look for:
- Startup errors
- Migration failures
- Database connection errors
- Provider configuration errors

**Worker logs:**
```bash
make logs-worker
# or
docker compose logs -f worker
```

Look for:
- Connection errors to Redis
- Job processing failures
- Provider errors

**Frontend dev server logs:**
- Check the terminal where `npm run dev` is running
- Look for proxy errors
- Look for compilation errors

#### 4. Browser Network Layer

Open browser DevTools (F12) → Network tab:

**Check requests:**
- Are requests being made to `/api/v1/...`?
- What is the status code?
  - `200` - Success
  - `404` - Route not found (check API version)
  - `403` - CORS error (check origin)
  - `429` - Rate limited
  - `503` - Service unavailable (API not ready)
  - `504` - Timeout (API too slow or unreachable)

**Check request details:**
- Click on a failed request
- Check the "Headers" tab
- Verify the request URL
- Check the response body for error details

#### 5. Configuration Layer

**Verify environment variables:**
```bash
# Check backend config
docker compose exec api env | grep AGENT_EDU

# Check frontend config
cat packages/frontend/.env  # if exists
```

**Common misconfigurations:**
- `AGENT_EDU_LLM_API_KEY` missing when using real provider
- `VITE_API_PROXY_TARGET` pointing to wrong port
- CORS origin mismatch (frontend not on localhost:5173)
- `AGENT_EDU_ALLOWED_SKILLS` missing required skills

#### 6. Data & Migration Layer

**Check database:**
```bash
# Connect to database
docker compose exec postgres psql -U agent_edu -d agent_edu

# Check if tables exist
\dt

# Exit
\q
```

**Check migrations:**
```bash
# Run migrations manually
make migrate

# Or check migration status
docker compose exec api alembic current
```

**Check Redis:**
```bash
# Connect to Redis
docker compose exec redis redis-cli

# Test connection
ping

# Exit
exit
```

---

## Common Issues

### Issue: Page Loads Indefinitely (Blank Spinner)

**Symptoms:** Frontend page shows loading spinner forever, no content appears.

**Diagnosis (in order):**

1. **Frontend not running**
   - Check: Is `npm run dev` running?
   - Fix: Start frontend dev server

2. **Vite proxy target incorrect**
   - Check: Browser Network tab shows requests to wrong port
   - Fix: Verify `VITE_API_PROXY_TARGET` or use default

3. **API healthz fails**
   - Check: `curl http://localhost:8000/healthz`
   - Fix: Check API logs, wait for startup, restart if needed

4. **API readyz fails**
   - Check: `curl http://localhost:8000/readyz`
   - Fix: Check database/Redis health, check migration logs

5. **Provider timeout**
   - Check: API logs show timeout errors
   - Fix: Check provider configuration, API key, network connectivity

6. **Worker not running**
   - Check: `docker compose ps` shows worker as running
   - Fix: Check worker logs, restart worker

### Issue: API Returns 403 Forbidden

**Symptoms:** Requests fail with 403 status code.

**Cause:** CORS error - frontend origin not allowed.

**Fix:**
- Ensure frontend is accessed from `http://localhost:5173`
- If using different port, update CORS in `packages/agent_core/src/agent_core/api/app.py`:
  ```python
  allow_origins=["http://localhost:5173", "http://localhost:3000"]
  ```

### Issue: Migration Failed

**Symptoms:** API logs show migration errors, readyz fails.

**Diagnosis:**
```bash
make logs-api
# Look for "alembic" or "migration" errors
```

**Fix:**
```bash
# Reset database (WARNING: destroys all data)
make dev-down
docker volume rm agent-edu_postgres-data
make dev-up

# Or run migrations manually
make migrate
```

### Issue: Worker Not Processing Jobs

**Symptoms:** Background tasks (memory maintenance, skill curation) don't run.

**Diagnosis:**
```bash
make logs-worker
# Look for connection errors or job failures
```

**Common causes:**
- Redis not reachable
- Worker started before API was healthy
- Job processing errors

**Fix:**
```bash
# Restart worker
docker compose restart worker

# Check worker logs
make logs-worker
```

### Issue: "Skill Not Enabled" Error

**Symptoms:** API returns error like `Skill 'plan_study_path' is not enabled.`

**Cause:** Skill not in `AGENT_EDU_ALLOWED_SKILLS` list.

**Fix:**
```bash
# Edit .env
AGENT_EDU_ALLOWED_SKILLS=explain_concept,create_quiz,adaptive_hint,plan_study_path,schedule_review

# Restart API
docker compose restart api
```

### Issue: Provider API Key Missing

**Symptoms:** LLM calls fail with authentication errors.

**Diagnosis:**
```bash
make logs-api
# Look for "API key" or "authentication" errors
```

**Fix:**
- Add API key to `.env`:
  ```bash
  AGENT_EDU_LLM_API_KEY=your-api-key
  ```
- Restart API:
  ```bash
  docker compose restart api
  ```

### Issue: Hot Reload Not Working

**Symptoms:** Code changes don't reflect in running application.

**Current behavior:**
- **API**: No hot reload in Docker mode. Must restart: `docker compose restart api`
- **Worker**: No hot reload. Must restart: `docker compose restart worker`
- **Frontend**: Hot reload works automatically with Vite

**For faster backend iteration:**
Use Mode B (Local Backend + Local Frontend) with `uvicorn --reload`.

---

## Observability

### Start Observability Stack

```bash
make observability-up
```

This starts:
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (admin/admin)

### View Metrics

- API metrics: http://localhost:8000/metrics
- Prometheus targets: http://localhost:9090/targets
- Grafana dashboards: http://localhost:3000/dashboards

### Stop Observability Stack

```bash
make observability-down
```

---

## Make Commands Reference

### Core Development

- `make dev-up` - Start backend stack (API, worker, postgres, redis)
- `make dev-down` - Stop backend stack
- `make ps` - Show status of all services
- `make logs-api` - Follow API logs
- `make logs-worker` - Follow worker logs

### Database

- `make migrate` - Run database migrations
- `make dev-down && docker volume rm agent-edu_postgres-data && make dev-up` - Reset database

### Testing

- `make test` - Run all unit tests
- `make test-api` - Run API integration tests
- `make docker-api-test` - Run Docker blackbox tests
- `make mvp-check` - Run MVP acceptance tests
- `make real-provider-regression` - Run real provider tests (requires API keys)

### Observability

- `make observability-up` - Start Prometheus and Grafana
- `make observability-down` - Stop observability stack

### Smoke Tests

- `make smoke-api` - Quick API health check
- `make smoke-stack` - Full stack verification

### Local Development

- `make install-local` - Install Python dependencies locally
- `make lint` - Run frontend linter

---

## Additional Resources

- [Docker Validation](DOCKER_VALIDATION.md) - Docker-specific testing and validation
- [Architecture](../ARCHITECTURE.md) - System architecture overview
- [System Design](SYSTEM_DESIGN.md) - Detailed system design document
- [API Documentation](http://localhost:8000/docs) - Interactive API docs (when backend is running)

---

## Getting Help

If you encounter issues not covered in this runbook:

1. Check the [troubleshooting section](#troubleshooting) again
2. Review logs: `make logs-api`, `make logs-worker`
3. Check existing issues in the repository
4. Ask in the project communication channel
