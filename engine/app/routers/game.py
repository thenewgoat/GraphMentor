"""Game launch endpoint — spawns iloveMons/Tuxemon as a local subprocess."""
import logging
import subprocess
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/game", tags=["game"])

_game_process: subprocess.Popen | None = None


def _is_running() -> bool:
    global _game_process
    if _game_process is None:
        return False
    if _game_process.poll() is not None:
        _game_process = None
        return False
    return True


@router.post("/launch/{course_id}/{node_id}")
def launch_game(course_id: UUID, node_id: UUID):
    # TODO: pass course_id/node_id to game process for quiz context
    global _game_process

    game_dir = Path(settings.game_path).resolve()
    entry = game_dir / "run_tuxemon.py"

    if not entry.exists():
        logger.error("Game entry point not found: %s", entry)
        raise HTTPException(status_code=404, detail="Game executable not found. Check game_path configuration.")

    if _is_running():
        logger.info("Game already running (pid=%d)", _game_process.pid)
        return {"status": "already_running"}

    venv_python = game_dir / ".venv" / "bin" / "python3"
    python_cmd = str(venv_python) if venv_python.exists() else "python3"

    _game_process = subprocess.Popen(
        [python_cmd, "run_tuxemon.py"],
        cwd=str(game_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    logger.info("Launching game for course=%s node=%s", course_id, node_id)

    return {"status": "launched"}
