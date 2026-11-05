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
        person_id = _extract_person_id(handler_input)
        user = config.resolve_user(person_id=person_id)
        name_greeting = f", {user['name']}" if user.get("name") else ""
        speak_output = (
            f"Bienvenido a Mi Micro{name_greeting}. Puedes preguntarme cuánto saldo le queda a tu Bip, "
            "dónde viene la micro, si alcanzas a salir, o decir: guarda mi tarjeta Bip. ¿Qué te gustaría saber?"
        )
        reprompt_text = "¿Deseas consultar tu saldo, ver cuándo viene tu micro o guardar una tarjeta?"

        return (
            handler_input.response_builder
            .speak(speak_output)
            .ask(reprompt_text)
            .set_card(SimpleCard("Mi Micro - Red Movilidad", "Consulta saldo Bip!, predictivo y configuración por voz"))
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

        raw_card = card_slot.value if card_slot and card_slot.value else None
        custom_nombre = nombre_slot.value if nombre_slot and nombre_slot.value else None

        person_id = _extract_person_id(handler_input)

        if raw_card:
            clean_card = config.clean_card_number(raw_card)
            speak_output = red_service.format_balance_speech(clean_card)
        else:
            user_info = config.resolve_user(name_query=custom_nombre, person_id=person_id)
            card = user_info.get("card", "")
            user_name = user_info.get("name", "Usuario")

            # Si no hay tarjeta guardada válida
            if not card:
                speak_output = (
                    f"Aún no tienes una tarjeta Bip registrada para {user_name}. "
                    "¿Cuál es el número de tu tarjeta Bip?"
                )
                return (
                    handler_input.response_builder
                    .speak(speak_output)
                    .ask("¿Cuál es el número de tu tarjeta Bip para guardarla?")
                    .response
                )

            speak_output = red_service.format_balance_speech(card, user_name=user_name)

        return (
            handler_input.response_builder
            .speak(speak_output)
            .set_card(SimpleCard("Saldo Tarjeta Bip!", speak_output))
            .response
        )


class GuardarTarjetaIntentHandler(AbstractRequestHandler):
    """Handler para guardar tarjeta por voz: 'Guarda mi tarjeta 12345678', 'La tarjeta de María es 87654321', etc."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("GuardarTarjetaIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        slots = handler_input.request_envelope.request.intent.slots or {}
        card_slot = slots.get("numeroTarjeta")
        nombre_slot = slots.get("nombre")

        raw_card = card_slot.value if card_slot and card_slot.value else None
        custom_nombre = nombre_slot.value if nombre_slot and nombre_slot.value else None
        person_id = _extract_person_id(handler_input)

        clean_card = config.clean_card_number(raw_card)

        if not clean_card or len(clean_card) < 6:
            speak_output = (
                "No alcancé a capturar bien los dígitos de tu tarjeta Bip. "
                "Por favor dime los números, por ejemplo diciendo: guarda mi tarjeta doce treinta y cuatro cincuenta y seis setenta y ocho."
            )
            return (
                handler_input.response_builder
                .speak(speak_output)
                .ask("¿Cuál es el número de tu tarjeta Bip?")
                .response
            )

        success, msg, user_info = config.save_card(
            card_number=clean_card,
            name_query=custom_nombre,
            person_id=person_id
        )

        user_name = user_info.get("name", "Usuario")

        # Consultar saldo en vivo para dar verificación inmediata al usuario
        balance_info = red_service.get_bip_balance(clean_card)
        if balance_info["success"] and balance_info["balance"] is not None:
            monto = f"{balance_info['balance']:,}".replace(",", ".")
            speak_output = (
                f"¡Listo! Guardé la tarjeta {clean_card} para {user_name}. "
                f"Su saldo actual es de {monto} pesos."
            )
        else:
            speak_output = (
                f"¡Listo! Guardé la tarjeta {clean_card} para {user_name}. "
                "Ya quedó registrada para tus próximas consultas."
            )

        return (
            handler_input.response_builder
            .speak(speak_output)
            .set_card(SimpleCard("Tarjeta Bip Guardada", speak_output))
            .response
        )


class ListarTarjetasIntentHandler(AbstractRequestHandler):
    """Handler para listar tarjetas: '¿Qué tarjetas tengo guardadas?', 'Cuáles son mis tarjetas', etc."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("ListarTarjetasIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        users = config.list_configured_users()
        if not users:
            speak_output = "No tienes tarjetas Bip registradas todavía. Puedes decir: guarda mi tarjeta, seguido del número."
        else:
            parts = []
            for u in users:
                masked = u["card_masked"].replace("...", "")
                parts.append(f"{u['name']} tiene la tarjeta terminada en {masked}")
            speak_output = f"Tienes {len(users)} tarjetas: " + "; y ".join(parts) + ". Puedes preguntar el saldo de cualquiera diciendo su nombre."

        return (
            handler_input.response_builder
            .speak(speak_output)
            .set_card(SimpleCard("Tarjetas Registradas", speak_output))
            .response
        )


class GuardarPreferenciaIntentHandler(AbstractRequestHandler):
    """Handler para guardar paradero o micro favorita: 'Guarda mi micro 401', 'Mi paradero es PA345'."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("GuardarPreferenciaIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        slots = handler_input.request_envelope.request.intent.slots or {}
        linea_slot = slots.get("linea")
        paradero_slot = slots.get("paradero")
        nombre_slot = slots.get("nombre")

        linea = linea_slot.value if linea_slot and linea_slot.value else None
        paradero = paradero_slot.value if paradero_slot and paradero_slot.value else None
        nombre = nombre_slot.value if nombre_slot and nombre_slot.value else None
        person_id = _extract_person_id(handler_input)

        if not linea and not paradero:
            speak_output = (
                "Para guardar tus preferencias puedes decir: "
                "guarda mi paradero PA tres cuatro cinco, o guarda mi micro cuatrocientos uno."
            )
            return (
                handler_input.response_builder
                .speak(speak_output)
                .ask("¿Qué paradero o micro deseas guardar?")
                .response
            )

        success, msg, user_info = config.save_preference(
            stop=paradero,
            service=linea,
            name_query=nombre,
            person_id=person_id
        )

        return (
            handler_input.response_builder
            .speak(msg)
            .set_card(SimpleCard("Preferencias Guardadas", msg))
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
            paradero = paradero_slot.value.replace(" ", "").replace(".", "").upper()
        else:
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
            "o preguntar: ¿alcanzo a salir? También puedes decir: guarda mi tarjeta Bip doce treinta y cuatro cincuenta y seis setenta y ocho."
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
