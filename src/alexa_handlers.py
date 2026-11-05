import logging
from ask_sdk_core.dispatch_components import (
    AbstractRequestHandler,
    AbstractExceptionHandler,
)
from ask_sdk_core.utils import is_request_type, is_intent_name
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response
from ask_sdk_model.ui import SimpleCard

import config
from src import red_service
from src import location_service

logger = logging.getLogger(__name__)


def _extract_person_id(handler_input: HandlerInput) -> str | None:
    """Extrae el person_id de Alexa Voice ID si el usuario tiene perfil de voz."""
    try:
        system = handler_input.request_envelope.context.system
        person = getattr(system, "person", None)
        return person.person_id if person else None
    except Exception:
        return None


class LaunchRequestHandler(AbstractRequestHandler):
    """Handler para cuando el usuario dice: 'Alexa, abre Mi Micro'."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        speak_output = (
            "Bienvenido a Mi Micro. Puedes preguntarme cuánto saldo le queda a tu Bip, "
            "dónde viene la micro o si alcanzas a salir. ¿Qué te gustaría saber?"
        )
        reprompt_text = "¿Deseas consultar tu saldo o cuándo llega tu micro habitual?"

        return (
            handler_input.response_builder
            .speak(speak_output)
            .ask(reprompt_text)
            .set_card(SimpleCard("Mi Micro - Red Movilidad", "Consulta saldo Bip! y predictivo de micros"))
            .response
        )


class SaldoBipIntentHandler(AbstractRequestHandler):
    """Handler para: '¿Cuánto saldo tengo?', 'Saldo de la Bip', 'Saldo de María', etc."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("SaldoBipIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        slots = handler_input.request_envelope.request.intent.slots or {}
        card_slot = slots.get("numeroTarjeta")
        nombre_slot = slots.get("nombre")

        custom_card = card_slot.value if card_slot and card_slot.value else None
        custom_nombre = nombre_slot.value if nombre_slot and nombre_slot.value else None

        person_id = _extract_person_id(handler_input)

        if custom_card:
            # Tarjeta dictada explícitamente por números
            speak_output = red_service.format_balance_speech(custom_card)
        else:
            # Resolver usuario por Voice ID o por nombre dictado ("de María", "de Simón")
            user_info = config.resolve_user(name_query=custom_nombre, person_id=person_id)
            speak_output = red_service.format_balance_speech(user_info["card"], user_name=user_info["name"])

        return (
            handler_input.response_builder
            .speak(speak_output)
            .set_card(SimpleCard("Saldo Tarjeta Bip!", speak_output))
            .response
        )


class PrediccionMicroIntentHandler(AbstractRequestHandler):
    """Handler para: '¿Dónde viene la micro?', '¿Cuánto le falta a la 401?', etc."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("PrediccionMicroIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        slots = handler_input.request_envelope.request.intent.slots or {}

        linea_slot = slots.get("linea")
        paradero_slot = slots.get("paradero")

        person_id = _extract_person_id(handler_input)
        user_info = config.resolve_user(person_id=person_id)

        linea = linea_slot.value if linea_slot and linea_slot.value else user_info["service"]

        distance_to_stop = None
        if paradero_slot and paradero_slot.value:
            # El usuario dictó un código de paradero específico
            paradero = paradero_slot.value.replace(" ", "").replace(".", "").upper()
        else:
            # Detección inteligente por ubicación de Alexa (GPS móvil o Dirección del Echo)
            paradero, _, distance_to_stop = location_service.resolve_stop_for_request(
                handler_input, fallback_stop=user_info["stop"]
            )

        speak_output = red_service.format_prediction_speech(paradero, linea, distance_to_stop=distance_to_stop)

        return (
            handler_input.response_builder
            .speak(speak_output)
            .set_card(SimpleCard(f"Llegada de Micro {linea.upper()}", speak_output))
            .response
        )


class ResumenViajeIntentHandler(AbstractRequestHandler):
    """Handler para: '¿Alcanzo a salir?', 'Estado de mi viaje', 'Alcanza Simón', etc."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("ResumenViajeIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        slots = handler_input.request_envelope.request.intent.slots or {}
        nombre_slot = slots.get("nombre")
        custom_nombre = nombre_slot.value if nombre_slot and nombre_slot.value else None

        person_id = _extract_person_id(handler_input)
        user_info = config.resolve_user(name_query=custom_nombre, person_id=person_id)

        # Detectar paradero por ubicación si es posible
        stop_code, _, distance_to_stop = location_service.resolve_stop_for_request(
            handler_input, fallback_stop=user_info["stop"]
        )

        speak_output = red_service.format_travel_summary_speech(
            user_name=user_info["name"],
            card_number=user_info["card"],
            stop_code=stop_code,
            service=user_info["service"],
            distance_to_stop=distance_to_stop
        )

        return (
            handler_input.response_builder
            .speak(speak_output)
            .set_card(SimpleCard("Resumen de Viaje", speak_output))
            .response
        )


class BusesEnRutaIntentHandler(AbstractRequestHandler):
    """Handler para: '¿Cuántos buses hay en la 401?', 'Buses activos 506', etc."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("BusesEnRutaIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        slots = handler_input.request_envelope.request.intent.slots
        linea_slot = slots.get("linea") if slots else None
        linea = linea_slot.value if linea_slot and linea_slot.value else config.DEFAULT_SERVICE

        buses = red_service.get_buses_on_route(linea)
        total = len(buses)

        if total > 0:
            speak_output = f"Hay {total} buses del recorrido {linea} circulando en este momento en Santiago."
        else:
            speak_output = f"No encontré buses activos circulando para el recorrido {linea}."

        return (
            handler_input.response_builder
            .speak(speak_output)
            .set_card(SimpleCard(f"Buses en Ruta {linea.upper()}", speak_output))
            .response
        )


class HelpIntentHandler(AbstractRequestHandler):
    """Handler para ayuda estándar de Alexa."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        speak_output = (
            "Puedes decir: cuánto saldo le queda a mi Bip, cuánto le falta a la 401, "
            "o preguntar: ¿alcanzo a salir? para revisar tu micro y tu saldo al mismo tiempo."
        )
        return (
            handler_input.response_builder
            .speak(speak_output)
            .ask(speak_output)
            .response
        )


class CancelOrStopIntentHandler(AbstractRequestHandler):
    """Handler para salir o cancelar."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            is_intent_name("AMAZON.CancelIntent")(handler_input) or
            is_intent_name("AMAZON.StopIntent")(handler_input)
        )

    def handle(self, handler_input: HandlerInput) -> Response:
        speak_output = "¡Buen viaje! Hasta pronto."
        return handler_input.response_builder.speak(speak_output).response


class SessionEndedRequestHandler(AbstractRequestHandler):
    """Handler para cierre de sesión."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        return handler_input.response_builder.response


class CatchAllExceptionHandler(AbstractExceptionHandler):
    """Captura cualquier excepción imprevista."""

    def can_handle(self, handler_input: HandlerInput, exception: Exception) -> bool:
        return True

    def handle(self, handler_input: HandlerInput, exception: Exception) -> Response:
        logger.error(f"Error procesando solicitud: {exception}", exc_info=True)
        speak_output = "Lo siento, tuve un problema al consultar la información de Red Movilidad. Intenta de nuevo en unos segundos."
        return (
            handler_input.response_builder
            .speak(speak_output)
            .ask("¿Quieres intentar de nuevo?")
            .response
        )
