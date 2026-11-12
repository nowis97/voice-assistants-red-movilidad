import base64
import os
import sys
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
from src import google_smarthome
from src.bus_watcher import watcher_manager


REDIRECT_URI = "https://oauth-redirect.googleusercontent.com/r/red-movilidad-project"


@pytest.fixture
def smarthome_client(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_ID", "client-123")
    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_SECRET", "super-secret-xyz")
    monkeypatch.setattr(config, "GOOGLE_OAUTH_PIN", "2468")
    monkeypatch.setattr(config, "GOOGLE_WATCH_THRESHOLD_MINUTES", 5)

    test_app = FastAPI()
    test_app.include_router(google_smarthome.router)
    yield TestClient(test_app)
    watcher_manager.cancel_watch("google_home")


def _obtain_tokens(client: TestClient):
    res_auth = client.post(
        "/google/oauth/auth",
        data={
            "client_id": "client-123",
            "redirect_uri": REDIRECT_URI,
            "state": "state-abc",
            "pin": "2468",
        },
        follow_redirects=False,
    )
    assert res_auth.status_code == 302
    loc = res_auth.headers["location"]
    parsed = urlparse(loc)
    qs = parse_qs(parsed.query)
    assert qs["state"] == ["state-abc"]
    code = qs["code"][0]

    res_tok = client.post(
        "/google/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": "client-123",
            "client_secret": "super-secret-xyz",
        },
    )
    assert res_tok.status_code == 200
    return res_tok.json()


def test_oauth_auth_requires_server_pin_configured(smarthome_client, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_OAUTH_PIN", "")
    res = smarthome_client.get(
        "/google/oauth/auth",
        params={"client_id": "client-123", "redirect_uri": REDIRECT_URI, "state": "s1", "response_type": "code"},
    )
    assert res.status_code == 503


def test_oauth_auth_rejects_disallowed_redirect_uri(smarthome_client):
    res = smarthome_client.get(
        "/google/oauth/auth",
        params={"client_id": "client-123", "redirect_uri": "https://evil.example.com/cb", "response_type": "code"},
    )
    assert res.status_code == 400


def test_oauth_auth_wrong_pin_returns_401(smarthome_client):
    res = smarthome_client.post(
        "/google/oauth/auth",
        data={
            "client_id": "client-123",
            "redirect_uri": REDIRECT_URI,
            "state": "state-1",
            "pin": "9999",
        },
        follow_redirects=False,
    )
    assert res.status_code == 401
    assert "PIN incorrecto" in res.text


def test_oauth_full_code_and_refresh_flow_including_basic_auth(smarthome_client):
    tokens = _obtain_tokens(smarthome_client)
    assert tokens["token_type"] == "Bearer"
    assert tokens["access_token"]
    assert tokens["refresh_token"]

    basic_creds = base64.b64encode(b"client-123:super-secret-xyz").decode("ascii")
    res_ref = smarthome_client.post(
        "/google/oauth/token",
        headers={"Authorization": f"Basic {basic_creds}"},
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
        },
    )
    assert res_ref.status_code == 200
    ref_body = res_ref.json()
    assert ref_body["access_token"]
    assert ref_body["token_type"] == "Bearer"


def test_oauth_token_rejects_bad_secret_and_tampered_refresh_token(smarthome_client):
    tokens = _obtain_tokens(smarthome_client)

    res_bad_secret = smarthome_client.post(
        "/google/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": "client-123",
            "client_secret": "wrong",
        },
    )
    assert res_bad_secret.status_code == 400
    assert res_bad_secret.json()["error"] == "invalid_client"

    res_bad_tok = smarthome_client.post(
        "/google/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"] + "tamper",
            "client_id": "client-123",
            "client_secret": "super-secret-xyz",
        },
    )
    assert res_bad_tok.status_code == 400
    assert res_bad_tok.json()["error"] == "invalid_grant"


def test_smarthome_rejects_missing_or_invalid_bearer(smarthome_client):
    payload = {"requestId": "req-1", "inputs": [{"intent": "action.devices.SYNC"}]}
    assert smarthome_client.post("/google/smarthome", json=payload).status_code == 401
    assert (
        smarthome_client.post(
            "/google/smarthome",
            headers={"Authorization": "Bearer bogus.token"},
            json=payload,
        ).status_code
        == 401
    )


def test_smarthome_sync_and_query_states(smarthome_client):
    access_token = _obtain_tokens(smarthome_client)["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    res_sync = smarthome_client.post(
        "/google/smarthome",
        headers=headers,
        json={"requestId": "req-sync", "inputs": [{"intent": "action.devices.SYNC"}]},
    )
    assert res_sync.status_code == 200
    sync_payload = res_sync.json()["payload"]
    device_ids = {d["id"] for d in sync_payload["devices"]}
    assert device_ids == {"red_saldo_bip", "red_micro_habitual", "red_alcanzo_salir", "red_vigilante"}

    res_query = smarthome_client.post(
        "/google/smarthome",
        headers=headers,
        json={
            "requestId": "req-query",
            "inputs": [
                {
                    "intent": "action.devices.QUERY",
                    "payload": {
                        "devices": [
                            {"id": "red_saldo_bip"},
                            {"id": "red_vigilante"},
                            {"id": "unknown_dev"},
                        ]
                    },
                }
            ],
        },
    )
    assert res_query.status_code == 200
    q_devs = res_query.json()["payload"]["devices"]
    assert q_devs["red_saldo_bip"]["on"] is False
    assert q_devs["red_vigilante"]["on"] is False
    assert q_devs["unknown_dev"]["status"] == "ERROR"


def test_smarthome_execute_returns_immediate_success_and_dispatches_thread(smarthome_client):
    access_token = _obtain_tokens(smarthome_client)["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    started_threads = []

    class ImmediateThread:
        def __init__(self, target=None, args=(), daemon=False):
            self.target = target
            self.args = args

        def start(self):
            started_threads.append((self.target, self.args))

    with patch("src.google_smarthome.threading.Thread", ImmediateThread):
        res_exec = smarthome_client.post(
            "/google/smarthome",
            headers=headers,
            json={
                "requestId": "req-exec",
                "inputs": [
                    {
                        "intent": "action.devices.EXECUTE",
                        "payload": {
                            "commands": [
                                {
                                    "devices": [{"id": "red_micro_habitual"}, {"id": "red_vigilante"}],
                                    "execution": [{"command": "action.devices.commands.OnOff", "params": {"on": True}}],
                                }
                            ]
                        },
                    }
                ],
            },
        )

    assert res_exec.status_code == 200
    commands = res_exec.json()["payload"]["commands"]
    by_id = {c["ids"][0]: c for c in commands}
    # Momentary trigger resets UI state to False
    assert by_id["red_micro_habitual"]["states"]["on"] is False
    assert by_id["red_vigilante"]["states"]["on"] is True
    assert started_threads == [
        (google_smarthome.execute_device_action, ("red_micro_habitual", True)),
        (google_smarthome.execute_device_action, ("red_vigilante", True)),
    ]


def test_execute_device_action_runs_all_four_devices(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_WATCH_THRESHOLD_MINUTES", 5)
    sample_user = {"name": "Simón", "card": "12345678", "stop": "PD289", "service": "513"}
    sample_stops = {
        "ida": {"code": "PD289", "name": "Paradero Ida"},
        "vuelta": {"code": "PD290", "name": "Paradero Vuelta"},
        "intersection": "José Arrieta con Ictinos",
    }

    with patch("src.google_smarthome.config.resolve_user", return_value=sample_user), \
         patch("src.google_smarthome.config.get_user_stops", return_value=sample_stops), \
         patch("src.google_smarthome.google_cast_service.speak_on_home", return_value=True) as mock_cast:

        with patch("src.google_smarthome.red_service.format_balance_speech", return_value="Saldo 3000"):
            google_smarthome.execute_device_action("red_saldo_bip", True)
            mock_cast.assert_called_with("Saldo 3000")

        with patch("src.google_smarthome.red_service.format_dual_prediction_speech", return_value="513 en 4m"):
            google_smarthome.execute_device_action("red_micro_habitual", True)
            mock_cast.assert_called_with("513 en 4m")

        with patch("src.google_smarthome.red_service.format_travel_summary_speech", return_value="Resumen OK"):
            google_smarthome.execute_device_action("red_alcanzo_salir", True)
            mock_cast.assert_called_with("Resumen OK")

        # Watcher ON starts monitor when bus is > threshold
        with patch(
            "src.google_smarthome.red_service.get_stop_predictions",
            return_value={"success": True, "buses": [{"min_time": 12}]},
        ), patch.object(watcher_manager, "start_watch") as mock_start:
            google_smarthome.execute_device_action("red_vigilante", True)
            assert mock_start.called
            assert mock_start.call_args.kwargs["notify_channel"] == "google_cast"
            assert mock_start.call_args.kwargs["user_id"] == "google_home"

        # Watcher OFF cancels monitor
        with patch.object(watcher_manager, "cancel_watch", return_value=True) as mock_cancel:
            google_smarthome.execute_device_action("red_vigilante", False)
            mock_cancel.assert_called_once_with("google_home")
            assert "cancelé" in mock_cast.call_args[0][0].lower()


def test_oauth_auth_get_rejects_bad_client_or_response_type(smarthome_client):
    res_bad_client = smarthome_client.get(
        "/google/oauth/auth",
        params={"client_id": "wrong-client", "redirect_uri": REDIRECT_URI, "state": "s1", "response_type": "code"},
    )
    assert res_bad_client.status_code == 400

    res_bad_type = smarthome_client.get(
        "/google/oauth/auth",
        params={"client_id": "client-123", "redirect_uri": REDIRECT_URI, "state": "s1", "response_type": "token"},
    )
    assert res_bad_type.status_code == 400


def test_oauth_auth_post_missing_config_and_disallowed_redirect(smarthome_client, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_OAUTH_PIN", "")
    res = smarthome_client.post(
        "/google/oauth/auth",
        data={"client_id": "client-123", "redirect_uri": REDIRECT_URI, "pin": "2468"},
    )
    assert res.status_code == 503

    monkeypatch.setattr(config, "GOOGLE_OAUTH_PIN", "2468")
    res_disallowed = smarthome_client.post(
        "/google/oauth/auth",
        data={"client_id": "client-123", "redirect_uri": "https://evil.com", "pin": "2468"},
    )
    assert res_disallowed.status_code == 400


def test_oauth_token_unsupported_grant_and_server_unconfigured(smarthome_client, monkeypatch):
    res = smarthome_client.post(
        "/google/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "client-123",
            "client_secret": "super-secret-xyz",
        },
    )
    assert res.status_code == 400
    assert res.json()["error"] == "unsupported_grant_type"

    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_SECRET", "")
    res_unconf = smarthome_client.post(
        "/google/oauth/token",
        data={"grant_type": "refresh_token", "client_id": "client-123", "client_secret": "super-secret-xyz"},
    )
    assert res_unconf.status_code == 503


def test_smarthome_disconnect_and_empty_inputs(smarthome_client):
    access_token = _obtain_tokens(smarthome_client)["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    res_disc = smarthome_client.post(
        "/google/smarthome",
        headers=headers,
        json={"requestId": "req-disc", "inputs": [{"intent": "action.devices.DISCONNECT"}]},
    )
    assert res_disc.status_code == 200
    assert res_disc.json() == {}

    res_empty = smarthome_client.post(
        "/google/smarthome",
        headers=headers,
        json={"requestId": "req-empty", "inputs": []},
    )
    assert res_empty.status_code == 400


def test_smarthome_execute_unsupported_command(smarthome_client):
    access_token = _obtain_tokens(smarthome_client)["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    res_cmd = smarthome_client.post(
        "/google/smarthome",
        headers=headers,
        json={
            "requestId": "req-exec",
            "inputs": [
                {
                    "intent": "action.devices.EXECUTE",
                    "payload": {
                        "commands": [
                            {
                                "devices": [{"id": "red_micro_habitual"}],
                                "execution": [{"command": "action.devices.commands.BrightnessAbsolute", "params": {}}],
                            }
                        ]
                    },
                }
            ],
        },
    )
    assert res_cmd.status_code == 200
    cmd_res = res_cmd.json()["payload"]["commands"][0]
    assert cmd_res["status"] == "ERROR"
    assert cmd_res["errorCode"] == "functionNotSupported"


def test_execute_device_action_momentary_off_and_immediate_arrival(monkeypatch):
    sample_user = {"name": "Simón", "card": "12345678", "stop": "PD289", "service": "513"}
    sample_stops = {"ida": {"code": "PD289", "name": "Paradero Ida"}, "vuelta": None, "intersection": "Esquina"}

    with patch("src.google_smarthome.config.resolve_user", return_value=sample_user), \
         patch("src.google_smarthome.config.get_user_stops", return_value=sample_stops), \
         patch("src.google_smarthome.google_cast_service.speak_on_home") as mock_cast:

        # Momentary off does not speak
        google_smarthome.execute_device_action("red_saldo_bip", False)
        assert not mock_cast.called

        # Vigilante on with bus already arriving (time <= threshold) speaks immediately
        with patch(
            "src.google_smarthome.red_service.get_stop_predictions",
            return_value={"success": True, "buses": [{"min_time": 2}]},
        ), patch.object(watcher_manager, "start_watch") as mock_start:
            google_smarthome.execute_device_action("red_vigilante", True)
            assert not mock_start.called
            assert "ya está muy cerca" in mock_cast.call_args[0][0]

