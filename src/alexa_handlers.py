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

logger = logging.getLogger(__name__)


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
    """Handler para: '¿Cuánto saldo tengo?', 'Saldo de la Bip', etc."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("SaldoBipIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        slots = handler_input.request_envelope.request.intent.slots
        card_slot = slots.get("numeroTarjeta") if slots else None
        custom_card = card_slot.value if card_slot and card_slot.value else None

        speak_output = red_service.format_balance_speech(custom_card)

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
        slots = handler_input.request_envelope.request.intent.slots

        linea_slot = slots.get("linea") if slots else None
        paradero_slot = slots.get("paradero") if slots else None

        linea = linea_slot.value if linea_slot and linea_slot.value else config.DEFAULT_SERVICE
        paradero = paradero_slot.value if paradero_slot and paradero_slot.value else config.DEFAULT_STOP_CODE

        # Limpiar paradero (Alexa puede escuchar "p a 3 4 5" con espacios)
        paradero_limpio = paradero.replace(" ", "").replace(".", "").upper()

        speak_output = red_service.format_prediction_speech(paradero_limpio, linea)

        return (
            handler_input.response_builder
            .speak(speak_output)
            .set_card(SimpleCard(f"Llegada de Micro {linea.upper()}", speak_output))
            .response
        )


class ResumenViajeIntentHandler(AbstractRequestHandler):
    """Handler para: '¿Alcanzo a salir?', 'Estado de mi viaje', etc."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("ResumenViajeIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        speak_output = red_service.format_travel_summary_speech()

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
