from fastapi import FastAPI
from sqlalchemy import text

from app.db.postgres import engine as db_engine
from app.db.vector import get_chroma_client
from app.routers.ingest import router as ingest_router
from app.routers.extract import router as extract_router

app = FastAPI(title="GraphMentor Engine", version="0.1.0")
app.include_router(ingest_router)
app.include_router(extract_router)


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
