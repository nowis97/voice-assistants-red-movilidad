import sys
import os
from unittest.mock import patch
import pytest

# Asegurar que la raíz del proyecto esté en el path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src import red_service
from src import location_service
import config


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
    speech = red_service.format_balance_speech("12345678", user_name="Simón")
    assert "Simón, tu tarjeta Bip tiene un saldo de" in speech
    assert "pesos" in speech


def test_format_prediction_speech():
    """Prueba del formateador de voz para predictivo con distancia."""
    speech = red_service.format_prediction_speech("PA345", "401", distance_to_stop=85)
    assert isinstance(speech, str)
    assert "85 metros" in speech


def test_format_travel_summary_speech():
    """Prueba del comando combinado con usuario y paradero."""
    speech = red_service.format_travel_summary_speech(user_name="María", stop_code="PC186", service="506")
    assert "María," in speech
    assert "506" in speech


def test_location_find_nearest_stop():
    """Prueba la búsqueda offline en menos de 2ms del paradero más cercano en Santiago."""
    # Coordenadas de Metro Los Leones / Providencia
    nearest = location_service.find_nearest_stop(-33.4223, -70.6095)
    assert nearest is not None
    assert "code" in nearest
    assert "name" in nearest
    assert isinstance(nearest["distance_meters"], int)
    assert nearest["distance_meters"] < 300


def test_user_resolution():
    """Prueba la resolución multi-usuario por nombre y por person_id."""
    u1 = config.resolve_user(name_query="Simón")
    assert u1["name"] == "Simón"

    u2 = config.resolve_user(name_query="maría")
    assert u2["name"] == "María"

    u_alias = config.resolve_user(name_query="pareja")
    assert u_alias["name"] == "María"


@patch("src.red_service.get_stop_predictions")
def test_format_dual_prediction_both_directions(mock_preds):
    def side_effect(stop_code, service):
        if stop_code == "PD184":
            return {
                "success": True,
                "stop_code": "PD184",
                "stop_name": "Av. Grecia / Esq. Salvador",
                "target_service": "513",
                "buses": [{"service": "513", "meters": 1200, "min_time": 4, "max_time": 6}],
                "raw_services_count": 1
            }
        else:
            return {
                "success": True,
                "stop_code": "PD200",
                "stop_name": "Av. Grecia / Esq. Salvador",
                "target_service": "513",
                "buses": [{"service": "513", "meters": 2500, "min_time": 10, "max_time": 12}],
                "raw_services_count": 1
            }

    mock_preds.side_effect = side_effect

    speech = red_service.format_dual_prediction_speech(
        linea="513",
        stop_ida={"code": "PD184", "name": "Avenida Grecia con Salvador"},
        stop_vuelta={"code": "PD200", "name": "Avenida Grecia con Salvador"},
        intersection="Avenida Grecia con Salvador"
    )

    assert "Para la 513 en Avenida Grecia con Salvador" in speech
    assert "paradero PD184" in speech
    assert "vereda del frente (paradero PD200)" in speech
    assert "6 minutos" in speech


@patch("src.red_service.get_stop_predictions")
def test_format_dual_prediction_specific_direction(mock_preds):
    mock_preds.return_value = {
        "success": True,
        "stop_code": "PD184",
        "stop_name": "Av. Grecia / Esq. Salvador",
        "target_service": "513",
        "buses": [{"service": "513", "meters": 800, "min_time": 3, "max_time": 4}],
        "raw_services_count": 1
    }

    speech = red_service.format_dual_prediction_speech(
        linea="513",
        stop_ida={"code": "PD184", "name": "Avenida Grecia con Salvador"},
        stop_vuelta={"code": "PD200", "name": "Avenida Grecia con Salvador"},
        intersection="Avenida Grecia con Salvador",
        sentido_query="ida"
    )

    assert "La 513 de ida viene en Avenida Grecia con Salvador" in speech
    assert "PD184" in speech
    assert "PD200" not in speech


@patch("src.red_service.get_stop_predictions")
def test_format_dual_prediction_vuelta_direction(mock_preds):
    mock_preds.return_value = {
        "success": True,
        "stop_code": "PD200",
        "stop_name": "Av. Grecia / Esq. Salvador",
        "target_service": "513",
        "buses": [{"service": "513", "meters": 500, "min_time": 2, "max_time": 3}],
        "raw_services_count": 1
    }

    speech = red_service.format_dual_prediction_speech(
        linea="513",
        stop_ida={"code": "PD184", "name": "Avenida Grecia con Salvador"},
        stop_vuelta={"code": "PD200", "name": "Avenida Grecia con Salvador"},
        intersection="Avenida Grecia con Salvador",
        sentido_query="vuelta"
    )

    assert "La 513 de vuelta viene en Avenida Grecia con Salvador" in speech
    assert "PD200" in speech
    assert "PD184" not in speech


@patch("src.red_service.get_stop_predictions")
def test_format_dual_prediction_no_buses_both(mock_preds):
    mock_preds.return_value = {
        "success": True,
        "stop_code": "PD184",
        "stop_name": "Av. Grecia / Esq. Salvador",
        "target_service": "513",
        "buses": [],
        "raw_services_count": 1
    }

    speech = red_service.format_dual_prediction_speech(
        linea="513",
        stop_ida={"code": "PD184", "name": "Avenida Grecia con Salvador"},
        stop_vuelta={"code": "PD200", "name": "Avenida Grecia con Salvador"},
        intersection="Avenida Grecia con Salvador"
    )

    assert "No hay buses del recorrido 513 aproximándose a tu esquina Avenida Grecia con Salvador en este momento." == speech

