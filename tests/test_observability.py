import sys
import os
import pytest
from unittest.mock import MagicMock

# Asegurar path de imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.observability import ObservabilityStore
from src.lambda_function import lambda_handler
from src.local_server import app
from fastapi.testclient import TestClient

def test_observability_store_record_and_get():
    store = ObservabilityStore(maxlen=3)
    assert len(store.get_events()) == 0

    store.record(
        request_type="IntentRequest",
        intent_name="RouteToDestinationIntent",
        slots={"Destination": "Metro Tobalaba"},
        user_id="amzn1.ask.account.TEST1234",
        speech="Para ir a Metro Tobalaba te sirve la 513",
        latency_ms=350,
        status="success"
    )

    events = store.get_events()
    assert len(events) == 1
    ev = events[0]
    assert ev["intent_name"] == "RouteToDestinationIntent"
    assert ev["slots"] == {"Destination": "Metro Tobalaba"}
    assert ev["user_id"] == "TEST1234"
    assert ev["latency_ms"] == 350
    assert ev["status"] == "success"


def test_observability_store_max_limit():
    store = ObservabilityStore(maxlen=2)
    store.record(request_type="LaunchRequest", speech="Hola")
    store.record(request_type="IntentRequest", intent_name="SaldoBipIntent", speech="Saldo 1000")
    store.record(request_type="IntentRequest", intent_name="PrediccionMicroIntent", speech="Micro en 5 min")

    events = store.get_events()
    assert len(events) == 2
    assert events[0]["intent_name"] == "PrediccionMicroIntent"
    assert events[1]["intent_name"] == "SaldoBipIntent"


def test_lambda_handler_records_observability_event():
    from src.observability import store
    store.clear()

    # Simular LaunchRequest a través de lambda_handler
    event = {
        "version": "1.0",
        "session": {
            "new": True,
            "sessionId": "amzn1.echo-api.session.test",
            "application": {"applicationId": "amzn1.ask.skill.test"},
            "user": {"userId": "amzn1.ask.account.TEST_USER_9999"}
        },
        "context": {
            "System": {
                "application": {"applicationId": "amzn1.ask.skill.test"},
                "user": {"userId": "amzn1.ask.account.TEST_USER_9999"},
                "device": {"deviceId": "test-device"}
            }
        },
        "request": {
            "type": "LaunchRequest",
            "requestId": "amzn1.echo-api.request.test",
            "timestamp": "2026-11-06T00:00:00Z",
            "locale": "es-US"
        }
    }

    res = lambda_handler(event, None)
    assert res is not None
    assert "response" in res

    events = store.get_events()
    assert len(events) >= 1
    ev = events[0]
    assert ev["request_type"] == "LaunchRequest"
    assert "Red Movilidad" in ev["speech"] or "Bienvenido" in ev["speech"]
    assert ev["latency_ms"] >= 0


def test_local_server_dashboard_and_logs_endpoints():
    client = TestClient(app)

    res_dash = client.get("/dashboard")
    assert res_dash.status_code == 200
    assert "text/html" in res_dash.headers["content-type"]
    assert "Red Movilidad" in res_dash.text
    assert "Observabilidad" in res_dash.text

    res_logs = client.get("/api/logs")
    assert res_logs.status_code == 200
    assert isinstance(res_logs.json(), list)

    res_clear = client.post("/api/logs/clear")
    assert res_clear.status_code == 200
    assert res_clear.json()["status"] == "ok"
