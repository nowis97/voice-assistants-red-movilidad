import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.lambda_function import lambda_handler


def create_mock_envelope(
    request_type: str,
    intent_name: str = None,
    slots: dict = None,
    person_id: str = None,
    geolocation: dict = None
):
    """Crea una estructura mock de request envelope de Alexa con soporte multi-usuario y geolocalización."""
    system_ctx = {
        "application": {"applicationId": "amzn1.ask.skill.test"},
        "user": {"userId": "amzn1.ask.account.test"},
        "device": {"deviceId": "amzn1.ask.device.test"}
    }
    if person_id:
        system_ctx["person"] = {"personId": person_id}

    context = {
        "System": system_ctx
    }
    if geolocation:
        context["Geolocation"] = geolocation

    envelope = {
        "version": "1.0",
        "session": {
            "new": True,
            "sessionId": "SessionId.test",
            "application": {"applicationId": "amzn1.ask.skill.test"},
            "user": {"userId": "amzn1.ask.account.test"}
        },
        "context": context,
        "request": {
            "type": request_type,
            "requestId": "EdxF.test",
            "timestamp": "2026-11-04T21:00:00Z",
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
    assert "tarjeta Bip tiene un saldo de" in output_speech


def test_saldo_bip_multiuser_by_name():
    """Prueba consulta de saldo mencionando el nombre del segundo usuario."""
    req = create_mock_envelope("IntentRequest", "SaldoBipIntent", {"nombre": "María"})
    resp = lambda_handler(req, None)
    output_speech = resp["response"]["outputSpeech"]["ssml"]
    assert "María" in output_speech
    assert "saldo de" in output_speech


def test_prediccion_micro_intent():
    req = create_mock_envelope("IntentRequest", "PrediccionMicroIntent", {"linea": "401", "paradero": "PA345"})
    resp = lambda_handler(req, None)
    output_speech = resp["response"]["outputSpeech"]["ssml"]
    assert "micro" in output_speech.lower() or "buses" in output_speech.lower()


def test_prediccion_micro_auto_location():
    """Prueba que sin paradero dictado, detecte el paradero por coordenadas GPS en el contexto."""
    geo = {
        "coordinate": {
            "latitudeInDegrees": -33.4223,
            "longitudeInDegrees": -70.6095,
            "accuracyInMeters": 10.0
        }
    }
    req = create_mock_envelope("IntentRequest", "PrediccionMicroIntent", {"linea": "401"}, geolocation=geo)
    resp = lambda_handler(req, None)
    output_speech = resp["response"]["outputSpeech"]["ssml"]
    # Debería haber resuelto un paradero real cercano
    assert "micro" in output_speech.lower() or "buses" in output_speech.lower()


def test_resumen_viaje_multiuser():
    """Prueba de resumen de viaje para un usuario específico."""
    req = create_mock_envelope("IntentRequest", "ResumenViajeIntent", {"nombre": "Simón"})
    resp = lambda_handler(req, None)
    output_speech = resp["response"]["outputSpeech"]["ssml"]
    assert "Simón" in output_speech
    assert "saldo" in output_speech.lower() or "micro" in output_speech.lower()


def test_guardar_tarjeta_voice():
    """Prueba que el usuario pueda registrar o actualizar su tarjeta Bip por voz."""
    req = create_mock_envelope("IntentRequest", "GuardarTarjetaIntent", {"numeroTarjeta": "21547896"})
    resp = lambda_handler(req, None)
    output_speech = resp["response"]["outputSpeech"]["ssml"]
    assert "Guardé la tarjeta 21547896" in output_speech


def test_guardar_tarjeta_multiuser_by_name():
    """Prueba registrar una tarjeta asignándola a otro nombre por voz."""
    req = create_mock_envelope(
        "IntentRequest",
        "GuardarTarjetaIntent",
        {"numeroTarjeta": "99887766", "nombre": "María"}
    )
    resp = lambda_handler(req, None)
    output_speech = resp["response"]["outputSpeech"]["ssml"]
    assert "María" in output_speech
    assert "99887766" in output_speech


def test_listar_tarjetas_voice():
    """Prueba listar las tarjetas configuradas."""
    req = create_mock_envelope("IntentRequest", "ListarTarjetasIntent")
    resp = lambda_handler(req, None)
    output_speech = resp["response"]["outputSpeech"]["ssml"]
    assert "tarjetas" in output_speech.lower()
    assert "Simón" in output_speech or "María" in output_speech


def test_guardar_preferencia_voice():
    """Prueba guardar paradero o recorrido preferido por voz."""
    req = create_mock_envelope(
        "IntentRequest",
        "GuardarPreferenciaIntent",
        {"paradero": "PA345", "linea": "401"}
    )
    resp = lambda_handler(req, None)
    output_speech = resp["response"]["outputSpeech"]["ssml"]
    assert "PA345" in output_speech
    assert "401" in output_speech

