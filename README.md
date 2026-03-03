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
6. **Start Quiz** — click "Start Quiz" on any concept node to launch the game.

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
│   └── tests/               # 145 pytest tests
├── web/                     # Next.js 14 frontend
│   ├── app/                 # Pages (home, upload, course detail, graph editor)
│   ├── components/          # React components (GraphCanvas, NodeSidebar, ...)
│   └── lib/                 # API client, types, ELK layout
├── iloveMons/               # Game module (Tuxemon fork, GPL v3 — see Third-Party Licenses)
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
uv run pytest tests/ -v     # 145 tests, requires PostgreSQL (graphmentor_test)
```

Tests use SAVEPOINT rollback (no state leakage between tests) and mock all OpenAI calls.

### Frontend type checking

```bash
cd web
pnpm exec tsc --noEmit
```

## Quiz Mode (iloveMons)

GraphMentor integrates a game-based quiz mode through [iloveMons](iloveMons/), a fork of [Tuxemon](https://github.com/Tuxemon/Tuxemon) — an open-source monster-fighting RPG built with Pygame.

Clicking **"Start Quiz"** on any concept node in the graph editor launches the game as a local desktop window. The backend spawns the game as a separate process; no browser plugin or Electron wrapper is required.

### Setup

```bash
cd iloveMons
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The backend auto-detects the venv at `iloveMons/.venv/bin/python3`. If the venv is missing, it falls back to the system `python3`.

### Modular Game Design

The game module is **pluggable**. GraphMentor does not embed or link the game into its own code — it launches it as an independent subprocess via a single configurable path (`GAME_PATH` env var, defaults to `../iloveMons`).

This means you can **swap in any game** that meets two requirements:

1. **A `run_<name>.py` entry point** — a Python script that launches the game.
2. **A `.venv/` with its dependencies** — or dependencies installed in the system Python.

To use a different game, set `GAME_PATH` in your `.env` to point at the game's directory. Any open-source Pygame, Pyglet, or terminal-based game will work. The game runs as its own process with its own window and lifecycle — GraphMentor only starts it.

## Third-Party Licenses

### iloveMons (Tuxemon fork)

The `iloveMons/` directory contains a fork of [Tuxemon](https://www.tuxemon.org), licensed under the **GNU General Public License v3.0 (GPL v3)**. See [`iloveMons/LICENSE`](iloveMons/LICENSE) for the full license text.

- **Code:** GPL v3+ — Copyright (C) 2014-2026 William Edwards, Benjamin Bean
- **Art/Assets:** Various licenses, primarily [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). See [`iloveMons/ATTRIBUTIONS.md`](iloveMons/ATTRIBUTIONS.md) for per-asset attribution.

GraphMentor launches Tuxemon as a **separate process** (not linked, embedded, or compiled together). The GPL license applies to the contents of the `iloveMons/` directory and any modifications made to it. GraphMentor's own code (in `engine/` and `web/`) is not subject to the GPL through this integration.

## Tech Stack

**Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0, PostgreSQL, ChromaDB, OpenAI (gpt-4o-mini), Alembic, PyMuPDF

**Frontend:** Next.js 14 (App Router), TypeScript, React Flow, ELK layout (elkjs), Tailwind CSS

**Tooling:** uv (Python), pnpm (Node), pytest, ruff

