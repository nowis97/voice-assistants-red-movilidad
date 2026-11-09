import time
import re
import logging
from typing import Optional
from ask_sdk_core.skill_builder import CustomSkillBuilder
from ask_sdk_core.dispatch_components import AbstractRequestInterceptor, AbstractResponseInterceptor
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response

from src.alexa_handlers import (
    LaunchRequestHandler,
    SaldoBipIntentHandler,
    GuardarTarjetaIntentHandler,
    ListarTarjetasIntentHandler,
    GuardarPreferenciaIntentHandler,
    PrediccionMicroIntentHandler,
    RouteToDestinationIntentHandler,
    WatchBusIntentHandler,
    CancelWatchIntentHandler,
    ResumenViajeIntentHandler,
    BusesEnRutaIntentHandler,
    HelpIntentHandler,
    CancelOrStopIntentHandler,
    SessionEndedRequestHandler,
    CatchAllExceptionHandler,
)
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("alexa")


class LoggingRequestInterceptor(AbstractRequestInterceptor):
    """Intercepta y registra detalles completos de la solicitud entrante."""
    def process(self, handler_input: HandlerInput) -> None:
        start_time = time.time()
        req_attrs = handler_input.attributes_manager.request_attributes
        req_attrs["_start_time"] = start_time

        req = handler_input.request_envelope.request
        req_id = getattr(req, "request_id", "N/A")
        locale = getattr(req, "locale", "N/A")
        req_type = getattr(req, "object_type", type(req).__name__)
        intent_name = getattr(getattr(req, "intent", None), "name", None)

        slots = {}
        if hasattr(req, "intent") and req.intent and getattr(req.intent, "slots", None):
            slots = {k: v.value for k, v in req.intent.slots.items() if v and v.value}

        user_id = None
        person_id = None
        try:
            user_id = handler_input.request_envelope.context.system.user.user_id
        except Exception:
            pass
        try:
            person = getattr(handler_input.request_envelope.context.system, "person", None)
            if person:
                person_id = getattr(person, "person_id", None)
        except Exception:
            pass

        req_attrs["_request_type"] = req_type
        req_attrs["_intent_name"] = intent_name
        req_attrs["_slots"] = slots
        req_attrs["_user_id"] = user_id

        user_label = user_id[-8:] if user_id else "Anon"
        person_label = f"VoiceID:{person_id[-8:]}" if person_id else "NoVoiceID"
        logger.info(
            f"[ALEXA IN] {intent_name or req_type} (ID: {req_id}) | "
            f"Slots: {slots} | User: {user_label} ({person_label}) | Locale: {locale}"
        )


class LoggingResponseInterceptor(AbstractResponseInterceptor):
    """Intercepta la respuesta saliente, mide la latencia y la registra en logs."""
    def process(self, handler_input: HandlerInput, response: Optional[Response] = None) -> None:
        req_attrs = handler_input.attributes_manager.request_attributes
        start_time = req_attrs.get("_start_time", time.time())
        latency_ms = int((time.time() - start_time) * 1000)

        speech_text = ""
        card_info = ""
        directives_count = 0
        if response:
            if response.output_speech:
                raw_speech = getattr(response.output_speech, "ssml", "") or getattr(response.output_speech, "text", "")
                speech_text = re.sub(r"<[^>]+>", "", raw_speech).strip()
            if getattr(response, "card", None):
                card_title = getattr(response.card, "title", type(response.card).__name__)
                card_info = f" | Card: '{card_title}'"
            if getattr(response, "directives", None):
                directives_count = len(response.directives)

        directives_str = f" | Directives: {directives_count}" if directives_count else ""
        logger.info(f"[ALEXA OUT] ({latency_ms}ms){card_info}{directives_str} -> «{speech_text}»")


sb = CustomSkillBuilder()

# Registrar interceptores globales
sb.add_global_request_interceptor(LoggingRequestInterceptor())
sb.add_global_response_interceptor(LoggingResponseInterceptor())

# Registrar Request Handlers
sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(SaldoBipIntentHandler())
sb.add_request_handler(GuardarTarjetaIntentHandler())
sb.add_request_handler(ListarTarjetasIntentHandler())
sb.add_request_handler(GuardarPreferenciaIntentHandler())
sb.add_request_handler(PrediccionMicroIntentHandler())
sb.add_request_handler(RouteToDestinationIntentHandler())
sb.add_request_handler(WatchBusIntentHandler())
sb.add_request_handler(CancelWatchIntentHandler())
sb.add_request_handler(ResumenViajeIntentHandler())
sb.add_request_handler(BusesEnRutaIntentHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(CancelOrStopIntentHandler())
sb.add_request_handler(SessionEndedRequestHandler())

# Registrar Exception Handler
sb.add_exception_handler(CatchAllExceptionHandler())

# Punto de entrada AWS Lambda
lambda_handler = sb.lambda_handler()
