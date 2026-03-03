# GraphMentor

GraphMentor transforms lecture PDFs into structured, dependency-aware knowledge graphs. Upload your course materials, and the system extracts a hierarchical topic outline, infers relationships between concepts, enriches thin topics with external knowledge, and presents everything in an interactive graph editor.

The long-term vision is an adaptive learning loop — quizzes, teaching phases, and mastery tracking — built on top of the generated graph. The current implementation covers the full ingestion pipeline, graph generation, and a functional editing UI.

## Quick Start

### Prerequisites

| Tool       | Version | Install                                            |
| ---------- | ------- | -------------------------------------------------- |
| Python     | 3.12+   |                                                    |
| Node.js    | 18+     | `nvm install --lts`                                |
| uv         | 0.10+   | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| pnpm       | 9+      | `npm install -g pnpm`                              |
| PostgreSQL | 14+     |                       |

### 1. Database

Start PostgreSQL (Docker or local), then initialize:

```bash
uv run scripts/init-db.py
```

This creates two databases: `graphmentor` (dev) and `graphmentor_test` (tests).

### 2. Environment

```bash
cp .env.example .env
```

Set your `OPENAI_API_KEY` in `.env`. Other variables have sensible defaults:

| Variable         | Default                                                          | Notes                    |
| ---------------- | ---------------------------------------------------------------- | ------------------------ |
| `DATABASE_URL`   | `postgresql://graphmentor:graphmentor@localhost:5432/graphmentor` |                          |
| `OPENAI_API_KEY` | —                                                                | Required for ingestion   |
| `LLM_MODEL`      | `gpt-4o-mini`                                                    |                          |
| `CHROMADB_MODE`   | `persistent`                                                     | `persistent` or `http`   |
| `CHROMADB_PATH`   | `./data/chromadb`                                                | Embedded mode only       |

### 3. Backend

```bash
cd engine
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

API docs at `http://localhost:8000/docs`.

### 4. Frontend

```bash
cd web
pnpm install
pnpm dev
```

Open `http://localhost:3000`.

## Usage

1. **Create a course** — give it a title on the home page.
2. **Upload PDFs** — add one or more lecture slide decks from the course detail page.
3. **Generate Graph** — builds a knowledge graph from all uploaded documents. Topic extraction runs in parallel across documents.
4. **View & Edit Graph** — interactive editor with drag-to-connect edges, inline rename, and node/edge CRUD.
5. **Enrich** (optional) — fills in thin topics with Wikipedia summaries.

## Project Structure

```
GraphMentor/
├── engine/                  # Python FastAPI backend
│   ├── app/
│   │   ├── models/          # SQLAlchemy models (Course, Document, Page, Node, ...)
│   │   ├── routers/         # API endpoints (courses, extract, ingest)
│   │   ├── services/        # Pipeline stages (graph_builder, enrich, organize, llm_client)
│   │   └── db/              # Database connections (postgres, chromadb)
│   ├── migrations/          # Alembic migrations
│   └── tests/               # 114 pytest tests
├── web/                     # Next.js 14 frontend
│   ├── app/                 # Pages (home, upload, course detail, graph editor)
│   ├── components/          # React components (GraphCanvas, NodeSidebar, ...)
│   └── lib/                 # API client, types, ELK layout
├── scripts/                 # Database init
├── docs/                    # Architecture docs, ADRs, plans (gitignored)
└── docker-compose.yml       # PostgreSQL + ChromaDB containers
```

See `docs/implementation.md` for a detailed walkthrough of what the system does and how.

## Development

### Monorepo tasks (from repo root)

```bash
uv run poe serve      # start backend
uv run poe test       # run pytest
uv run poe migrate    # alembic upgrade head
```

### Running tests

```bash
cd engine
uv run pytest tests/ -v     # 114 tests, requires PostgreSQL (graphmentor_test)
```

Tests use SAVEPOINT rollback (no state leakage between tests) and mock all OpenAI calls.

### Frontend type checking

```bash
cd web
pnpm exec tsc --noEmit
```

## Tech Stack

**Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0, PostgreSQL, ChromaDB, OpenAI (gpt-4o-mini), Alembic, PyMuPDF

**Frontend:** Next.js 14 (App Router), TypeScript, React Flow, ELK layout (elkjs), Tailwind CSS

**Tooling:** uv (Python), pnpm (Node), pytest, ruff

