import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.lambda_function import lambda_handler


def create_mock_envelope(request_type: str, intent_name: str = None, slots: dict = None):
    """Crea una estructura mock de request envelope de Alexa."""
    envelope = {
        "version": "1.0",
        "session": {
            "new": True,
            "sessionId": "SessionId.test",
            "application": {"applicationId": "amzn1.ask.skill.test"},
            "user": {"userId": "amzn1.ask.account.test"}
        },
        "request": {
            "type": request_type,
            "requestId": "EdxF.test",
            "timestamp": "2026-11-03T21:00:00Z",
            "locale": "es-ES"
        }
    }
    if intent_name:
        formatted_slots = {}
        if slots:
            for k, v in slots.items():
                formatted_slots[k] = {"name": k, "value": v}

        envelope["request"]["intent"] = {
            "name": intent_name,
            "confirmationStatus": "NONE",
            "slots": formatted_slots
        }
    return envelope


def test_launch_request():
    req = create_mock_envelope("LaunchRequest")
    resp = lambda_handler(req, None)
    output_speech = resp["response"]["outputSpeech"]["ssml"]
    assert "Bienvenido a Mi Micro" in output_speech


def test_saldo_bip_intent():
    req = create_mock_envelope("IntentRequest", "SaldoBipIntent", {"numeroTarjeta": "12345678"})
    resp = lambda_handler(req, None)
    output_speech = resp["response"]["outputSpeech"]["ssml"]
    assert "Tu tarjeta Bip tiene un saldo de" in output_speech


def test_prediccion_micro_intent():
    req = create_mock_envelope("IntentRequest", "PrediccionMicroIntent", {"linea": "401", "paradero": "PA345"})
    resp = lambda_handler(req, None)
    output_speech = resp["response"]["outputSpeech"]["ssml"]
    assert "micro" in output_speech.lower() or "buses" in output_speech.lower()


def test_resumen_viaje_intent():
    req = create_mock_envelope("IntentRequest", "ResumenViajeIntent")
    resp = lambda_handler(req, None)
    output_speech = resp["response"]["outputSpeech"]["ssml"]
    assert "saldo" in output_speech.lower() or "micro" in output_speech.lower()
