# Agent-Edu Frontend

The web frontend for Agent-Edu, built with React, TypeScript, Vite, and Tailwind CSS.

## Quick Start

```bash
# Install dependencies
npm install

# Start development server (requires backend to be running)
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

## Prerequisites

The backend API must be running before starting the frontend. The recommended setup is:

```bash
# From the repository root
make dev-up
```

This starts the backend stack (API, worker, PostgreSQL, Redis) in Docker.

## Configuration

### API Connection

The frontend connects to the backend API through Vite's dev proxy:

- **Development**: Requests to `/api/*` are proxied to `http://localhost:8000`
- **Production**: API base URL defaults to `http://localhost:8000/api/v1`

Environment variables (optional):

- `VITE_API_PROXY_TARGET`: Override the proxy target (default: `http://localhost:8000`)
- `VITE_API_BASE_URL`: Override the API base URL (only needed for non-standard setups)

### CORS

The backend CORS configuration allows requests from `http://localhost:5173`. If you need to run the frontend on a different port, update the `allow_origins` in `packages/agent_core/src/agent_core/api/app.py`.

## Available Scripts

- `npm run dev` - Start development server with hot reload
- `npm run build` - Build for production
- `npm run preview` - Preview production build locally
- `npm run lint` - Run ESLint

## Project Structure

```
src/
├── api/          # API client and types
├── components/   # Reusable UI components
├── pages/        # Route pages
│   ├── goals/    # Learning goals
│   ├── sessions/ # Learning sessions
│   ├── learning/ # Learning workspace
│   └── operator/ # Operator dashboard
└── lib/          # Utilities and shared logic
```

## Troubleshooting

If you encounter issues:

1. **Page loading indefinitely**: Check that the backend is running (`make dev-up`) and healthy (`curl http://localhost:8000/healthz`)
2. **API errors**: Verify the API proxy target matches your backend port
3. **CORS errors**: Ensure you're accessing the frontend from `http://localhost:5173`

See [`../../docs/LOCAL_DEV_RUNBOOK.md`](../../docs/LOCAL_DEV_RUNBOOK.md) for comprehensive troubleshooting guidance.

## Documentation

- [Local Development Runbook](../../docs/LOCAL_DEV_RUNBOOK.md) - Complete setup and troubleshooting guide
- [Architecture](../../ARCHITECTURE.md) - System architecture overview
- [API Documentation](http://localhost:8000/docs) - Interactive API docs (when backend is running)
