import pytest
from unittest.mock import patch, MagicMock
from src.reminders_service import create_spoken_reminder, has_reminder_permission


def test_create_spoken_reminder_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"alertToken": "amzn1.reminder.test1234"}

    with patch("requests.post", return_value=mock_resp) as mock_post:
        res = create_spoken_reminder(
            api_endpoint="https://api.amazonalexa.com",
            api_access_token="test_token",
            text="Tu micro 513 está a 4 minutos",
            locale="es-US"
        )
        assert res["success"] is True
        assert res["alert_token"] == "amzn1.reminder.test1234"
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://api.amazonalexa.com/v1/alerts/reminders"
        assert kwargs["headers"]["Authorization"] == "Bearer test_token"
        assert kwargs["headers"]["Content-Type"] == "application/json"
        payload = kwargs["json"]
        assert payload["trigger"]["type"] == "SCHEDULED_RELATIVE"
        assert payload["trigger"]["offsetInSeconds"] == 0
        assert payload["alertInfo"]["spokenInfo"]["content"][0]["text"] == "Tu micro 513 está a 4 minutos"
        assert payload["alertInfo"]["spokenInfo"]["content"][0]["locale"] == "es-US"
        assert payload["pushNotification"]["status"] == "ENABLED"


def test_create_spoken_reminder_unauthorized():
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = "Forbidden"

    with patch("requests.post", return_value=mock_resp):
        res = create_spoken_reminder(
            api_endpoint="https://api.amazonalexa.com",
            api_access_token="invalid_token",
            text="Tu micro viene",
            locale="es-US"
        )
        assert res["success"] is False
        assert "403" in res["error"]


def test_create_spoken_reminder_exception():
    import requests
    with patch("requests.post", side_effect=requests.RequestException("Timeout")):
        res = create_spoken_reminder(
            api_endpoint="https://api.amazonalexa.com",
            api_access_token="test_token",
            text="Tu micro viene"
        )
        assert res["success"] is False
        assert "Timeout" in res["error"]


def test_has_reminder_permission_true():
    handler_input = MagicMock()
    # Case 1: permission consent token present
    handler_input.request_envelope.context.system.user.permissions.consent_token = "valid_consent_token"
    handler_input.request_envelope.context.system.api_access_token = "api_token"
    assert has_reminder_permission(handler_input) is True


def test_has_reminder_permission_false():
    handler_input = MagicMock()
    handler_input.request_envelope.context.system.user.permissions = None
    assert has_reminder_permission(handler_input) is False

    handler_input.request_envelope.context.system.user.permissions = MagicMock(consent_token=None)
    assert has_reminder_permission(handler_input) is False
