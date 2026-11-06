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


def test_plan_trip_direct_route():
    from src.red_service import plan_trip
    mock_response = [
        {
            "duration": 1560,
            "transfers": 0,
            "legs": [
                {
                    "mode": "WALK",
                    "distance": 120.0,
                    "to": {"name": "PD184-Parada / Salvador", "stopId": "PD184"}
                },
                {
                    "mode": "BUS",
                    "route": "513",
                    "from": {"name": "PD184-Parada / Salvador", "stopId": "PD184"},
                    "to": {"name": "PC2-Parada 7 / (M) Pedro de Valdivia", "stopId": "PC2"},
                    "duration": 1200.0
                },
                {
                    "mode": "WALK",
                    "distance": 80.0,
                    "to": {"name": "Destination"}
                }
            ]
        }
    ]

    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_response

        res = plan_trip(-33.4578, -70.5891, -33.4225, -70.6094)
        assert res["success"] is True
        assert res["total_itineraries"] == 1
        assert len(res["direct_routes"]) == 1
        direct = res["direct_routes"][0]
        assert direct["route"] == "513"
        assert direct["from_stop_id"] == "PD184"
        assert direct["walk_distance_meters"] == 120
        assert direct["duration_minutes"] == 26


def test_plan_trip_transfer_route():
    from src.red_service import plan_trip
    mock_response = [
        {
            "duration": 2100,
            "transfers": 1,
            "legs": [
                {
                    "mode": "WALK",
                    "distance": 90.0,
                    "to": {"name": "PD184", "stopId": "PD184"}
                },
                {
                    "mode": "BUS",
                    "route": "506",
                    "from": {"name": "PD184", "stopId": "PD184"},
                    "to": {"name": "PC86-Plaza Italia", "stopId": "PC86"}
                },
                {
                    "mode": "WALK",
                    "distance": 50.0,
                    "to": {"name": "PA383", "stopId": "PA383"}
                },
                {
                    "mode": "BUS",
                    "route": "405",
                    "from": {"name": "PA383", "stopId": "PA383"},
                    "to": {"name": "PC153", "stopId": "PC153"}
                }
            ]
        }
    ]

    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_response

        res = plan_trip(-33.4578, -70.5891, -33.4000, -70.5500)
        assert res["success"] is True
        assert len(res["direct_routes"]) == 0
        assert len(res["transfer_routes"]) == 1
        transfer = res["transfer_routes"][0]
        assert transfer["first_route"] == "506"
        assert transfer["first_stop_id"] == "PD184"
        assert transfer["transfer_point"] == "Plaza Italia"
        assert transfer["second_route"] == "405"
        assert transfer["duration_minutes"] == 35


def test_plan_trip_network_error():
    import requests
    from src.red_service import plan_trip

    with patch("requests.get", side_effect=requests.RequestException("Timeout")):
        res = plan_trip(-33.4578, -70.5891, -33.4000, -70.5500)
        assert res["success"] is False
        assert "error" in res
        assert res["direct_routes"] == []
        assert res["transfer_routes"] == []


def test_format_route_speech_direct_with_live_buses():
    from src.red_service import format_route_speech

    mock_plan = {
        "success": True,
        "direct_routes": [
            {
                "mode": "BUS",
                "route": "513",
                "from_stop_id": "PD184",
                "from_stop_name": "Avenida Grecia con Salvador",
                "walk_distance_meters": 120,
                "duration_minutes": 25
            }
        ],
        "transfer_routes": [],
        "total_itineraries": 1
    }

    mock_pred = {
        "success": True,
        "buses": [
            {"service": "513", "min_time": 4, "max_time": 4, "meters": 800}
        ]
    }

    with patch("src.red_service.plan_trip", return_value=mock_plan), \
         patch("src.red_service.get_stop_predictions", return_value=mock_pred):
        speech = format_route_speech("Pedro de Valdivia con Providencia", -33.4578, -70.5891, -33.4225, -70.6094)
        assert "513" in speech
        assert "P D 184" in speech
        assert "4 minutos" in speech
        assert "25 minutos" in speech


def test_format_route_speech_transfer():
    from src.red_service import format_route_speech

    mock_plan = {
        "success": True,
        "direct_routes": [],
        "transfer_routes": [
            {
                "first_mode": "BUS",
                "first_route": "506",
                "first_stop_id": "PD184",
                "first_stop_name": "Avenida Grecia con Salvador",
                "transfer_point": "Plaza Italia",
                "second_mode": "BUS",
                "second_route": "405",
                "duration_minutes": 38,
                "walk_distance_meters": 90
            }
        ],
        "total_itineraries": 1
    }

    mock_pred = {
        "success": True,
        "buses": [
            {"service": "506", "min_time": 5, "max_time": 5, "meters": 1200}
        ]
    }

    with patch("src.red_service.plan_trip", return_value=mock_plan), \
         patch("src.red_service.get_stop_predictions", return_value=mock_pred):
        speech = format_route_speech("Vitacura", -33.4578, -70.5891, -33.4000, -70.5500)
        assert "no hay micro directa" in speech
        assert "506" in speech
        assert "P D 184" in speech
        assert "Plaza Italia" in speech
        assert "405" in speech
        assert "38 minutos" in speech


def test_format_route_speech_walking_distance():
    from src.red_service import format_route_speech
    # Distancia menor a 150m entre origen y destino
    speech = format_route_speech("La esquina de al lado", -33.4578, -70.5891, -33.4579, -70.5892)
    assert "caminando" in speech



