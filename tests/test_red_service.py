import sys
import os
import pytest

# Asegurar que la raíz del proyecto esté en el path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src import red_service


def test_get_bip_balance_live():
    """Prueba de consulta de saldo real contra el endpoint de Red Movilidad."""
    res = red_service.get_bip_balance("12345678")
    assert res["success"] is True
    assert isinstance(res["balance"], (int, float))
    assert res["card_number"] == "12345678"
    assert "$" in res["formatted_balance"]


def test_get_bip_balance_invalid():
    """Prueba con tarjeta inválida."""
    res = red_service.get_bip_balance("abc")
    assert res["success"] is False
    assert res["balance"] is None


def test_get_stop_predictions_live():
    """Prueba de predictivo de paraderos real (PA345 - Metro U de Chile)."""
    res = red_service.get_stop_predictions("PA345")
    assert res["success"] is True
    assert res["stop_code"] == "PA345"
    assert "UNIVERSIDAD DE CHILE" in res["stop_name"].upper()
    assert isinstance(res["buses"], list)


def test_get_stop_predictions_with_service():
    """Prueba de predictivo filtrando por servicio específico."""
    res = red_service.get_stop_predictions("PA345", service="401")
    assert res["success"] is True
    assert res["target_service"] == "401"
    for b in res["buses"]:
        assert b["service"] == "401"


def test_get_buses_on_route_live():
    """Prueba de telemetría GPS de buses activos en ruta 401."""
    buses = red_service.get_buses_on_route("401")
    assert isinstance(buses, list)
    if buses:
        bus = buses[0]
        assert "licensePlate" in bus
        assert "latitude" in bus
        assert "longitude" in bus
        assert bus["route"] == "401"


def test_format_balance_speech():
    """Prueba del formateador de voz para saldo."""
    speech = red_service.format_balance_speech("12345678")
    assert "Tu tarjeta Bip tiene un saldo de" in speech
    assert "pesos" in speech


def test_format_prediction_speech():
    """Prueba del formateador de voz para predictivo."""
    speech = red_service.format_prediction_speech("PA345", "401")
    assert isinstance(speech, str)
    assert len(speech) > 10


def test_format_travel_summary_speech():
    """Prueba del comando combinado 'alcanzo a salir'."""
    speech = red_service.format_travel_summary_speech()
    assert isinstance(speech, str)
    assert len(speech) > 10
