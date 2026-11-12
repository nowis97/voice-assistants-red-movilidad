import sys
import os
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.local_server import app
from src.bus_watcher import watcher_manager


def test_server_healthcheck_endpoints():
    client = TestClient(app)

    res_root = client.get("/")
    assert res_root.status_code == 200
    assert res_root.json()["status"] == "ok"

    res_alexa = client.get("/alexa")
    assert res_alexa.status_code == 200
    assert res_alexa.json()["status"] == "ok"


def test_server_alexa_webhook_post():
    client = TestClient(app)

    event = {
        "version": "1.0",
        "session": {
            "new": True,
            "sessionId": "amzn1.echo-api.session.test",
            "application": {"applicationId": "amzn1.ask.skill.test"},
            "user": {"userId": "amzn1.ask.account.TEST_USER"}
        },
        "context": {
            "System": {
                "application": {"applicationId": "amzn1.ask.skill.test"},
                "user": {"userId": "amzn1.ask.account.TEST_USER"},
                "device": {"deviceId": "test-device"}
            }
        },
        "request": {
            "type": "LaunchRequest",
            "requestId": "amzn1.echo-api.request.test",
            "timestamp": "2026-11-09T00:00:00Z",
            "locale": "es-US"
        }
    }

    res = client.post("/alexa", json=event)
    assert res.status_code == 200
    data = res.json()
    assert "response" in data
    assert "outputSpeech" in data["response"]


def test_watcher_api_endpoints():
    client = TestClient(app)

    watcher_manager.start_watch(
        user_id="user_api_test",
        linea="513",
        stop_code="PD289",
        corner_name="José Arrieta",
        threshold_minutes=5,
        api_endpoint="http://api.amazonalexa.com",
        api_access_token="tok123"
    )

    res_active = client.get("/api/watcher/active")
    assert res_active.status_code == 200
    jobs = res_active.json()
    assert len(jobs) >= 1
    assert any(j["user_id"] == "user_api_test" for j in jobs)

    res_cancel = client.post("/api/watcher/cancel?user_id=user_api_test")
    assert res_cancel.status_code == 200
    assert res_cancel.json()["status"] == "ok"
    assert watcher_manager.has_active_job("user_api_test") is False


def test_quick_api_endpoints():
    client = TestClient(app)

    with patch("src.red_service.get_bip_balance", return_value={"success": True, "balance": 1500}):
        res_saldo = client.get("/api/saldo?card=12345678")
        assert res_saldo.status_code == 200
        assert res_saldo.json()["balance"] == 1500

    with patch("src.red_service.get_stop_predictions", return_value={"success": True, "buses": []}):
        res_micro = client.get("/api/micro?paradero=PD289&linea=513")
        assert res_micro.status_code == 200
        assert res_micro.json()["success"] is True


def test_tts_clip_and_cast_devices_endpoints():
    from src import google_cast_service

    client = TestClient(app)

    try:
        assert client.get("/api/tts/nonexistent.mp3").status_code == 404

        with patch("src.google_cast_service.gTTS") as mock_gtts:
            mock_gtts.return_value.write_to_fp.side_effect = lambda fp: fp.write(b"ID3_FAKE_MP3")
            clip_id = google_cast_service.create_tts_clip("Prueba de audio")

        res_mp3 = client.get(f"/api/tts/{clip_id}.mp3")
        assert res_mp3.status_code == 200
        assert res_mp3.headers["content-type"].startswith("audio/mpeg")
        assert res_mp3.content == b"ID3_FAKE_MP3"

        with patch(
            "src.google_cast_service.list_cast_devices",
            return_value=[{"name": "Parlante Living", "cast_type": "audio"}],
        ):
            res_cast = client.get("/api/cast/devices")
        assert res_cast.status_code == 200
        assert res_cast.json() == {"devices": [{"name": "Parlante Living", "cast_type": "audio"}]}

        # Smoke check verifying google_smarthome.router is mounted on app
        res_smarthome_smoke = client.get("/google/oauth/auth")
        assert res_smarthome_smoke.status_code != 404
    finally:
        google_cast_service.clear_tts_clips()

