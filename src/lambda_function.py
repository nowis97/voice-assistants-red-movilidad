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
from src import observability
import config

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class LoggingRequestInterceptor(AbstractRequestInterceptor):
    """Intercepta y registra detalles completos de la solicitud entrante."""
    def process(self, handler_input: HandlerInput) -> None:
        start_time = time.time()
        req_attrs = handler_input.attributes_manager.request_attributes
        req_attrs["_start_time"] = start_time

        req = handler_input.request_envelope.request
        req_type = getattr(req, "object_type", type(req).__name__)
        intent_name = getattr(getattr(req, "intent", None), "name", None)

        slots = {}
        if hasattr(req, "intent") and req.intent and getattr(req.intent, "slots", None):
            slots = {k: v.value for k, v in req.intent.slots.items() if v and v.value}

        user_id = None
        try:
            user_id = handler_input.request_envelope.context.system.user.user_id
        except Exception:
            pass

        req_attrs["_request_type"] = req_type
        req_attrs["_intent_name"] = intent_name
        req_attrs["_slots"] = slots
        req_attrs["_user_id"] = user_id

        logger.info(f"[ALEXA IN] Request: {intent_name or req_type} | Slots: {slots} | User: {user_id[-8:] if user_id else 'Anon'}")


class LoggingResponseInterceptor(AbstractResponseInterceptor):
    """Intercepta la respuesta saliente, mide la latencia y la registra en el buffer de observabilidad."""
    def process(self, handler_input: HandlerInput, response: Optional[Response] = None) -> None:
        req_attrs = handler_input.attributes_manager.request_attributes
        start_time = req_attrs.get("_start_time", time.time())
        latency_ms = int((time.time() - start_time) * 1000)

        speech_text = ""
        if response and response.output_speech:
            raw_speech = getattr(response.output_speech, "ssml", "") or getattr(response.output_speech, "text", "")
            # Limpiar etiquetas SSML para lectura humana limpia
            speech_text = re.sub(r"<[^>]+>", "", raw_speech).strip()

        req_type = req_attrs.get("_request_type", "Unknown")
        intent_name = req_attrs.get("_intent_name") or req_type
        slots = req_attrs.get("_slots", {})
        user_id = req_attrs.get("_user_id")

        logger.info(f"[ALEXA OUT] ({latency_ms}ms) -> {speech_text[:140]}")

        # Guardar en el buffer circular de observabilidad
        observability.store.record(
            request_type=req_type,
            intent_name=intent_name,
            slots=slots,
            user_id=user_id,
            speech=speech_text,
            latency_ms=latency_ms,
            status="success"
        )


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
