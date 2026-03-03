"""FastAPI application with CORS, health check, and router registration."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.db.postgres import engine as db_engine
from app.db.vector import get_chroma_client
from app.routers.ingest import router as ingest_router
from app.routers.extract import router as extract_router
from app.routers.courses import router as courses_router
from app.routers.game import router as game_router

app = FastAPI(title="GraphMentor Engine", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(ingest_router)
app.include_router(extract_router)
app.include_router(courses_router)
app.include_router(game_router)


@app.get("/health")
def health():
    checks = {}

    # PostgreSQL
    try:
        with db_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"

    # ChromaDB
    try:
        client = get_chroma_client()
        client.heartbeat()
        checks["chromadb"] = "ok"
    except Exception as e:
        checks["chromadb"] = f"error: {e}"

    status = "healthy" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}
