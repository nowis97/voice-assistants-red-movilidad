import sys
import os
import pytest
from unittest.mock import patch
from ask_sdk_model import RequestEnvelope, Context, Application
from ask_sdk_model.interfaces.system import SystemState as System
from ask_sdk_model.intent import Intent
from ask_sdk_model.intent_request import IntentRequest
from ask_sdk_model.slot import Slot
from ask_sdk_core.handler_input import HandlerInput
from src.alexa_handlers import PrediccionMicroIntentHandler

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
    assert "Bienvenido a Red Movilidad" in output_speech


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


def test_guardar_preferencia_alphanumeric_spoken_voice():
    """Prueba que frases habladas como 'be 02' y 'pe a tres cuatro cinco' se guarden alfanuméricamente como B02 y PA345."""
    req = create_mock_envelope(
        "IntentRequest",
        "GuardarPreferenciaIntent",
        {"paradero": "pe a 345", "linea": "be 02"}
    )
    resp = lambda_handler(req, None)
    output_speech = resp["response"]["outputSpeech"]["ssml"]
    assert "PA345" in output_speech
    assert "B02" in output_speech


@patch("src.red_service.format_dual_prediction_speech")
@patch("config.get_user_stops")
def test_prediccion_micro_intent_dual_stops(mock_stops, mock_speech):
    mock_stops.return_value = {
        "ida": {"code": "PD184", "name": "Avenida Grecia con Salvador"},
        "vuelta": {"code": "PD200", "name": "Avenida Grecia con Salvador"},
        "intersection": "Avenida Grecia con Salvador"
    }
    mock_speech.return_value = "Para la 513 en Avenida Grecia con Salvador..."

    req_obj = IntentRequest(
        request_id="r1",
        timestamp="2026-11-05T00:00:00Z",
        intent=Intent(
            name="PrediccionMicroIntent",
            slots={"linea": Slot(name="linea", value="513")}
        )
    )
    envelope = RequestEnvelope(request=req_obj, context=Context(system=System(application=Application("app1"))))
    handler = PrediccionMicroIntentHandler()
    assert handler.can_handle(HandlerInput(request_envelope=envelope))
    resp = handler.handle(HandlerInput(request_envelope=envelope))
    assert "Para la 513 en Avenida Grecia con Salvador..." in resp.output_speech.ssml

    # Probar también invocación vía lambda_handler
    req = create_mock_envelope("IntentRequest", "PrediccionMicroIntent", {"linea": "513"})
    resp_lambda = lambda_handler(req, None)
    output_speech = resp_lambda["response"]["outputSpeech"]["ssml"]
    assert "Para la 513 en Avenida Grecia con Salvador..." in output_speech


@patch("src.red_service.format_dual_prediction_speech")
@patch("config.get_user_stops")
def test_prediccion_micro_intent_with_sentido(mock_stops, mock_speech):
    mock_stops.return_value = {
        "ida": {"code": "PD184", "name": "Avenida Grecia con Salvador"},
        "vuelta": {"code": "PD200", "name": "Avenida Grecia con Salvador"},
        "intersection": "Avenida Grecia con Salvador"
    }
    mock_speech.return_value = "La 513 de vuelta viene a 200 metros..."

    req = create_mock_envelope(
        "IntentRequest",
        "PrediccionMicroIntent",
        {"linea": "513", "sentido": "vuelta"}
    )
    resp = lambda_handler(req, None)
    output_speech = resp["response"]["outputSpeech"]["ssml"]
    assert "La 513 de vuelta viene a 200 metros..." in output_speech
    mock_speech.assert_called_with(
        linea="513",
        stop_ida={"code": "PD184", "name": "Avenida Grecia con Salvador"},
        stop_vuelta={"code": "PD200", "name": "Avenida Grecia con Salvador"},
        intersection="Avenida Grecia con Salvador",
        sentido_query="vuelta"
    )


@patch("config.save_stops_pair")
@patch("src.location_service.find_stops_by_intersection")
def test_guardar_preferencia_intersection(mock_find, mock_save):
    mock_find.return_value = (
        {"code": "PD184", "name": "Avenida Grecia con Salvador"},
        {"code": "PD200", "name": "Avenida Grecia con Salvador"}
    )
    mock_save.return_value = (
        True,
        "Guardé tu esquina Avenida Grecia con Salvador para Simón: paradero de ida PD184 y de vuelta PD200.",
        {"name": "Simón"}
    )

    req = create_mock_envelope(
        "IntentRequest",
        "GuardarPreferenciaIntent",
        {"calleUno": "Grecia", "calleDos": "Salvador"}
    )
    resp = lambda_handler(req, None)
    output_speech = resp["response"]["outputSpeech"]["ssml"]
    assert "PD184" in output_speech
    assert "PD200" in output_speech
    mock_find.assert_called_once_with("Grecia", "Salvador")
    mock_save.assert_called_once()


@patch("config.save_stops_pair")
@patch("src.location_service.find_opposing_stop")
def test_guardar_preferencia_single_stop_opposing_discovery(mock_opposing, mock_save):
    mock_opposing.return_value = {
        "code": "PC186",
        "name": "Avenida Apoquindo con El Bosque Norte"
    }
    mock_save.return_value = (
        True,
        "Guardé tu esquina Avenida Apoquindo con El Bosque Norte para Simón: paradero de ida PC185 y de vuelta PC186.",
        {"name": "Simón"}
    )

    req = create_mock_envelope(
        "IntentRequest",
        "GuardarPreferenciaIntent",
        {"paradero": "PC185"}
    )
    resp = lambda_handler(req, None)
    output_speech = resp["response"]["outputSpeech"]["ssml"]
    assert "PC185" in output_speech
    assert "PC186" in output_speech
    mock_opposing.assert_called_once_with("PC185")


def test_route_to_destination_intent_handler():
    from src.alexa_handlers import RouteToDestinationIntentHandler
    from ask_sdk_core.handler_input import HandlerInput
    from ask_sdk_model import RequestEnvelope, IntentRequest, Intent, Slot

    req = IntentRequest(
        intent=Intent(
            name="RouteToDestinationIntent",
            slots={
                "Destination": Slot(name="Destination", value="Metro Tobalaba")
            }
        )
    )
    envelope = RequestEnvelope(request=req)
    handler_input = HandlerInput(request_envelope=envelope)

    handler = RouteToDestinationIntentHandler()
    assert handler.can_handle(handler_input) is True

    with patch("src.alexa_handlers.geocode_address", return_value=(-33.4179, -70.6016)), \
         patch("src.alexa_handlers.format_route_speech", return_value="Para ir a Metro Tobalaba te sirve la 513."):
        resp = handler.handle(handler_input)
        assert "513" in resp.output_speech.ssml


def test_route_to_destination_no_slot():
    from src.alexa_handlers import RouteToDestinationIntentHandler
    from ask_sdk_core.handler_input import HandlerInput
    from ask_sdk_model import RequestEnvelope, IntentRequest, Intent, Slot

    req = IntentRequest(
        intent=Intent(
            name="RouteToDestinationIntent",
            slots={
                "Destination": Slot(name="Destination", value=None)
            }
        )
    )
    envelope = RequestEnvelope(request=req)
    handler_input = HandlerInput(request_envelope=envelope)

    handler = RouteToDestinationIntentHandler()
    resp = handler.handle(handler_input)
    assert "Por favor dime a qué dirección, esquina o lugar quieres ir." in resp.output_speech.ssml
    assert "¿A dónde deseas ir?" in resp.reprompt.output_speech.ssml


def test_route_to_destination_geocode_failed():
    from src.alexa_handlers import RouteToDestinationIntentHandler
    from ask_sdk_core.handler_input import HandlerInput
    from ask_sdk_model import RequestEnvelope, IntentRequest, Intent, Slot

    req = IntentRequest(
        intent=Intent(
            name="RouteToDestinationIntent",
            slots={
                "Destination": Slot(name="Destination", value="Calle Inexistente 9999")
            }
        )
    )
    envelope = RequestEnvelope(request=req)
    handler_input = HandlerInput(request_envelope=envelope)

    handler = RouteToDestinationIntentHandler()
    with patch("src.alexa_handlers.geocode_address", return_value=None):
        resp = handler.handle(handler_input)
        assert "No pude encontrar la dirección o esquina Calle Inexistente 9999" in resp.output_speech.ssml
        assert "Providencia con Pedro de Valdivia" in resp.output_speech.ssml


def test_route_to_destination_via_lambda_handler():
    req = create_mock_envelope(
        "IntentRequest",
        "RouteToDestinationIntent",
        {"Destination": "Metro Tobalaba"}
    )
    with patch("src.alexa_handlers.geocode_address", return_value=(-33.4179, -70.6016)), \
         patch("src.alexa_handlers.format_route_speech", return_value="Para ir a Metro Tobalaba te sirve la 513."):
        resp = lambda_handler(req, None)
        output_speech = resp["response"]["outputSpeech"]["ssml"]
        assert "513" in output_speech


def test_watch_bus_intent_handler_without_permission():
    from src.alexa_handlers import WatchBusIntentHandler
    from ask_sdk_core.handler_input import HandlerInput
    from ask_sdk_model import RequestEnvelope, IntentRequest, Intent, Slot, Context, User
    from ask_sdk_model.interfaces.system import SystemState as System

    req = IntentRequest(
        intent=Intent(
            name="WatchBusIntent",
            slots={"linea": Slot(name="linea", value="513")}
        )
    )
    context = Context(system=System(user=User(user_id="user_test_no_perm")))
    handler_input = HandlerInput(request_envelope=RequestEnvelope(request=req, context=context))

    handler = WatchBusIntentHandler()
    assert handler.can_handle(handler_input) is True
    res = handler.handle(handler_input)
    assert "permiso" in res.output_speech.ssml.lower()


def test_watch_bus_intent_handler_already_arriving():
    from src.alexa_handlers import WatchBusIntentHandler
    from ask_sdk_core.handler_input import HandlerInput
    from ask_sdk_model import RequestEnvelope, IntentRequest, Intent, Slot, Context, User, Permissions
    from ask_sdk_model.interfaces.system import SystemState as System

    req = IntentRequest(
        intent=Intent(
            name="WatchBusIntent",
            slots={"linea": Slot(name="linea", value="513")}
        )
    )
    user = User(user_id="user_test_perm", permissions=Permissions(consent_token="valid_consent"))
    system = System(user=user, api_endpoint="https://api.amazonalexa.com", api_access_token="tok123")
    context = Context(system=system)
    handler_input = HandlerInput(request_envelope=RequestEnvelope(request=req, context=context))

    handler = WatchBusIntentHandler()

    mock_pred = {
        "success": True,
        "buses": [{"service": "513", "min_time": 2, "max_time": 3, "meters": 400}]
    }

    with patch("src.red_service.get_stop_predictions", return_value=mock_pred):
        res = handler.handle(handler_input)
        assert "salir ahora mismo" in res.output_speech.ssml.lower() or "cerca" in res.output_speech.ssml.lower()


def test_watch_bus_intent_handler_starts_watching():
    from src.alexa_handlers import WatchBusIntentHandler
    from src.bus_watcher import watcher_manager
    from ask_sdk_core.handler_input import HandlerInput
    from ask_sdk_model import RequestEnvelope, IntentRequest, Intent, Slot, Context, User, Permissions
    from ask_sdk_model.interfaces.system import SystemState as System

    req = IntentRequest(
        intent=Intent(
            name="WatchBusIntent",
            slots={
                "linea": Slot(name="linea", value="513"),
                "tiempo": Slot(name="tiempo", value="8")
            }
        )
    )
    user = User(user_id="user_watch_ok", permissions=Permissions(consent_token="valid_consent"))
    system = System(user=user, api_endpoint="https://api.amazonalexa.com", api_access_token="tok_abc")
    context = Context(system=system)
    handler_input = HandlerInput(request_envelope=RequestEnvelope(request=req, context=context))

    handler = WatchBusIntentHandler()

    mock_pred = {
        "success": True,
        "buses": [{"service": "513", "min_time": 15, "max_time": 20, "meters": 3500}]
    }

    with patch("src.red_service.get_stop_predictions", return_value=mock_pred):
        res = handler.handle(handler_input)
        assert "vigilando" in res.output_speech.ssml.lower()
        assert watcher_manager.has_active_job("user_watch_ok") is True

    watcher_manager.cancel_watch("user_watch_ok")


def test_cancel_watch_intent_handler():
    from src.alexa_handlers import CancelWatchIntentHandler
    from src.bus_watcher import watcher_manager
    from ask_sdk_core.handler_input import HandlerInput
    from ask_sdk_model import RequestEnvelope, IntentRequest, Intent, Context, User
    from ask_sdk_model.interfaces.system import SystemState as System

    watcher_manager.start_watch("user_cancel_test", "513", "PD289", "José Arrieta", 5, "http://api", "token")
    assert watcher_manager.has_active_job("user_cancel_test") is True

    req = IntentRequest(intent=Intent(name="CancelWatchIntent"))
    context = Context(system=System(user=User(user_id="user_cancel_test")))
    handler_input = HandlerInput(request_envelope=RequestEnvelope(request=req, context=context))

    handler = CancelWatchIntentHandler()
    assert handler.can_handle(handler_input) is True
    res = handler.handle(handler_input)
    assert "cancel" in res.output_speech.ssml.lower()
    assert watcher_manager.has_active_job("user_cancel_test") is False






