# Agent-Edu

**Agent-Edu** is a production-grade educational agent codebase designed to evolve from a stable teaching agent into a governed multi-agent learning companion with memory, reflection, and controlled capability growth.

For detailed architecture, system design, and the evolutionary roadmap, please refer to:
- [System Design Document](docs/SYSTEM_DESIGN.md)
- [Architecture Blueprint](ARCHITECTURE.md)
- [Agent Rules & Constraints](AGENTS.md)

---

## Prerequisites

- **Docker** and **Docker Compose**
- **Make**
- (Optional) Python 3.10+ for local development without Docker
- (Optional) Node.js for frontend linting

## Quick Start (Docker)

The easiest way to run the project is using Docker Compose.

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd agent-edu
   ```

2. **Environment Configuration:**
   Copy the example environment file and adjust if necessary.
   ```bash
   cp .env.example .env
   ```

3. **Start the development environment:**
   ```bash
   make dev-up
   ```
   This will build the API image, start the PostgreSQL database, Redis, and the FastAPI application.

4. **View Logs:**
   ```bash
   make logs
   ```

5. **Stop the environment:**
   ```bash
   make dev-down
   ```

## Observability

The project includes Prometheus and Grafana for metrics and observability.
To start the observability stack alongside the API:

```bash
make observability-up
```
- Grafana is available at: `http://localhost:3000` (Default credentials: `admin` / `admin`)
- Prometheus is available at: `http://localhost:9090`

To stop the observability stack:
```bash
make observability-down
```

## Running Tests

We provide several test suites that can be run entirely within Docker:

- **Run all unit tests:**
  ```bash
  make test
  ```

- **Run API integration tests:**
  ```bash
  make test-api
  ```

- **Run Docker Blackbox tests:**
  ```bash
  make docker-api-test
  ```

- **Run tests against real LLM providers:** (Requires real API keys in `.env`)
  ```bash
  make real-provider-regression
  ```

## Local Development (Without Docker)

If you prefer to run the API locally without Docker:

1. **Start infrastructure dependencies (Postgres & Redis):**
   ```bash
   docker compose up -d postgres redis
   ```

2. **Install dependencies:**
   ```bash
   make install-local
   ```

3. **Run database migrations:**
   ```bash
   alembic upgrade head
   ```

4. **Start the API:**
   ```bash
   uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000
   ```

## Documentation

- Architecture details: `ARCHITECTURE.md`
- Project Agent Rules: `AGENTS.md`
- Coding Conventions: `CONVENTIONS.md`
- System Design (Old README): `docs/SYSTEM_DESIGN.md`
- Additional documentation in the `docs/` folder.
