"""Tests for the game launch endpoint."""
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import game as game_module


@pytest.fixture(autouse=True)
def reset_game_process():
    """Reset the global _game_process between tests."""
    game_module._game_process = None
    yield
    game_module._game_process = None


@pytest.fixture
def client():
    return TestClient(app)


class TestGameLaunchEndpoint:
    def test_launch_game_success(self, client):
        course_id = uuid.uuid4()
        node_id = uuid.uuid4()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None

        with patch("app.routers.game.Path.exists", return_value=True), \
             patch("app.routers.game.subprocess.Popen", return_value=mock_proc) as mock_popen:
            response = client.post(f"/game/launch/{course_id}/{node_id}")

        assert response.status_code == 200
        assert response.json() == {"status": "launched"}
        mock_popen.assert_called_once()

    def test_launch_game_already_running(self, client):
        course_id = uuid.uuid4()
        node_id = uuid.uuid4()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # process still running

        with patch("app.routers.game.Path.exists", return_value=True), \
             patch("app.routers.game.subprocess.Popen", return_value=mock_proc):
            # First launch
            resp1 = client.post(f"/game/launch/{course_id}/{node_id}")
            assert resp1.status_code == 200
            assert resp1.json() == {"status": "launched"}

            # Second launch while still running
            resp2 = client.post(f"/game/launch/{course_id}/{node_id}")
            assert resp2.status_code == 200
            assert resp2.json() == {"status": "already_running"}

    def test_launch_game_not_found(self, client):
        course_id = uuid.uuid4()
        node_id = uuid.uuid4()

        with patch("app.routers.game.Path.exists", return_value=False):
            response = client.post(f"/game/launch/{course_id}/{node_id}")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
