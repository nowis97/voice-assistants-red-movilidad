from ask_sdk_core.skill_builder import CustomSkillBuilder
from ask_sdk_core.dispatch_components import AbstractRequestInterceptor
from ask_sdk_core.handler_input import HandlerInput
import logging

from src.alexa_handlers import (
    LaunchRequestHandler,
    SaldoBipIntentHandler,
    GuardarTarjetaIntentHandler,
    ListarTarjetasIntentHandler,
    GuardarPreferenciaIntentHandler,
    PrediccionMicroIntentHandler,
    RouteToDestinationIntentHandler,
    ResumenViajeIntentHandler,
    BusesEnRutaIntentHandler,
    HelpIntentHandler,
    CancelOrStopIntentHandler,
    SessionEndedRequestHandler,
    CatchAllExceptionHandler,
)
import config

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class LoggingRequestInterceptor(AbstractRequestInterceptor):
    def process(self, handler_input: HandlerInput) -> None:
        req = handler_input.request_envelope.request
        logger.info(f"Incoming Request: {getattr(req, 'object_type', type(req).__name__)}")


sb = CustomSkillBuilder()

# Registrar interceptores
sb.add_global_request_interceptor(LoggingRequestInterceptor())

# Registrar Request Handlers
sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(SaldoBipIntentHandler())
sb.add_request_handler(GuardarTarjetaIntentHandler())
sb.add_request_handler(ListarTarjetasIntentHandler())
sb.add_request_handler(GuardarPreferenciaIntentHandler())
sb.add_request_handler(PrediccionMicroIntentHandler())
sb.add_request_handler(RouteToDestinationIntentHandler())
sb.add_request_handler(ResumenViajeIntentHandler())
sb.add_request_handler(BusesEnRutaIntentHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(CancelOrStopIntentHandler())
sb.add_request_handler(SessionEndedRequestHandler())

# Registrar Exception Handler
sb.add_exception_handler(CatchAllExceptionHandler())

# Punto de entrada AWS Lambda
lambda_handler = sb.lambda_handler()
