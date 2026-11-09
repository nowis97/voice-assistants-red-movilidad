import logging
import re
import sqlite3
import os
from ask_sdk_core.dispatch_components import (
    AbstractRequestHandler,
    AbstractExceptionHandler,
)
from ask_sdk_core.utils import is_request_type, is_intent_name
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response
from ask_sdk_model.ui import SimpleCard, AskForPermissionsConsentCard

import config
from src import red_service
from src import location_service
from src import reminders_service
from src.bus_watcher import watcher_manager
from src.location_service import (
    geocode_address,
    normalize_destination_query,
    get_coordinates_from_request,
)
from src.red_service import format_route_speech

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
    """Handler para cuando el usuario dice: 'Alexa, abre Red Movilidad'."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        person_id = _extract_person_id(handler_input)
        user = config.resolve_user(person_id=person_id)
        name_greeting = f", {user['name']}" if user.get("name") else ""
        speak_output = (
            f"Bienvenido a Red Movilidad{name_greeting}. Puedes preguntarme cuánto saldo le queda a tu Bip, "
            "dónde viene tu micro de ida o vuelta, o decir: mi esquina es Grecia con Salvador. ¿Qué te gustaría saber?"
        )
        reprompt_text = "¿Deseas consultar tu saldo, ver cuándo viene tu micro o configurar tu esquina?"

        return (
            handler_input.response_builder
            .speak(speak_output)
            .ask(reprompt_text)
            .set_card(SimpleCard("Red Movilidad", "Consulta saldo Bip!, predictivo y paraderos de ida y vuelta"))
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
    """Handler para guardar paradero, micro favorita o esquina/intersección: 'Guarda mi micro 401', 'Mi paradero es PA345', 'Mi esquina es Grecia con Salvador'."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("GuardarPreferenciaIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        slots = handler_input.request_envelope.request.intent.slots or {}
        linea_slot = slots.get("linea")
        paradero_slot = slots.get("paradero")
        nombre_slot = slots.get("nombre")
        esquina_slot = slots.get("esquina")
        calle_uno_slot = slots.get("calleUno")
        calle_dos_slot = slots.get("calleDos")

        linea = linea_slot.value if linea_slot and linea_slot.value else None
        paradero = paradero_slot.value if paradero_slot and paradero_slot.value else None
        nombre = nombre_slot.value if nombre_slot and nombre_slot.value else None
        esquina = esquina_slot.value if esquina_slot and esquina_slot.value else None
        calle_uno = calle_uno_slot.value if calle_uno_slot and calle_uno_slot.value else None
        calle_dos = calle_dos_slot.value if calle_dos_slot and calle_dos_slot.value else None
        person_id = _extract_person_id(handler_input)
        target_key = nombre or (person_id or "user1")

        # 1. Caso Esquina / Dos calles
        calle1, calle2 = None, None
        if calle_uno or calle_dos:
            calle1 = calle_uno or ""
            calle2 = calle_dos or ""
        elif esquina:
            norm_esq = esquina.strip()
            if " con " in norm_esq.lower():
                parts = re.split(r"\s+con\s+", norm_esq, maxsplit=1, flags=re.IGNORECASE)
                calle1, calle2 = parts[0], parts[1]
            elif " y " in norm_esq.lower():
                parts = re.split(r"\s+y\s+", norm_esq, maxsplit=1, flags=re.IGNORECASE)
                calle1, calle2 = parts[0], parts[1]
            elif "/" in norm_esq:
                parts = norm_esq.split("/", 1)
                calle1, calle2 = parts[0], parts[1]
            else:
                calle1, calle2 = norm_esq, ""

        if calle1:
            stop_ida, stop_vuelta = location_service.find_stops_by_intersection(calle1, calle2)
            if not stop_ida:
                speak_output = f"No encontré paraderos para la esquina de {calle1} con {calle2}. Por favor verifica las calles e intenta de nuevo."
                return (
                    handler_input.response_builder
                    .speak(speak_output)
                    .set_card(SimpleCard("Esquina No Encontrada", speak_output))
                    .response
                )

            intersection_name = f"{calle1} con {calle2}".strip() if calle2 else calle1
            success, msg, user_info = config.save_stops_pair(
                target_key=target_key,
                stop_ida=stop_ida,
                stop_vuelta=stop_vuelta,
                intersection=intersection_name
            )
            if linea:
                clean_linea = config.clean_alphanumeric_code(linea)
                config.save_preference(service=clean_linea, name_query=nombre, person_id=person_id)
                msg += f" Y guardé tu micro {clean_linea}."

            return (
                handler_input.response_builder
                .speak(msg)
                .set_card(SimpleCard("Preferencias Guardadas", msg))
                .response
            )

        # 2. Caso Paradero específico dictado
        if paradero:
            clean_paradero = config.clean_alphanumeric_code(paradero)
            opposing = location_service.find_opposing_stop(clean_paradero)

            if opposing:
                stop_ida = {"code": clean_paradero, "name": opposing.get("name", clean_paradero)}
                success, msg, user_info = config.save_stops_pair(
                    target_key=target_key,
                    stop_ida=stop_ida,
                    stop_vuelta=opposing,
                    intersection=opposing.get("name")
                )
            else:
                stop_ida = {"code": clean_paradero, "name": clean_paradero}
                success, msg, user_info = config.save_stops_pair(
                    target_key=target_key,
                    stop_ida=stop_ida,
                    stop_vuelta=None,
                    intersection=clean_paradero
                )

            if linea:
                clean_linea = config.clean_alphanumeric_code(linea)
                config.save_preference(service=clean_linea, name_query=nombre, person_id=person_id)
                msg += f" Y guardé tu recorrido {clean_linea}."

            return (
                handler_input.response_builder
                .speak(msg)
                .set_card(SimpleCard("Preferencias Guardadas", msg))
                .response
            )

        # 3. Caso Solo micro/línea
        if linea:
            clean_linea = config.clean_alphanumeric_code(linea)
            success, msg, user_info = config.save_preference(
                service=clean_linea,
                name_query=nombre,
                person_id=person_id
            )
            return (
                handler_input.response_builder
                .speak(msg)
                .set_card(SimpleCard("Preferencias Guardadas", msg))
                .response
            )

        # 4. Caso nada dictado
        speak_output = (
            "Para guardar tus preferencias puedes decir: "
            "mi esquina es Grecia con Salvador, guarda mi paradero PA tres cuatro cinco, o guarda mi micro cuatrocientos uno."
        )
        return (
            handler_input.response_builder
            .speak(speak_output)
            .ask("¿Qué esquina, paradero o micro deseas guardar?")
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
        sentido_slot = slots.get("sentido")

        person_id = _extract_person_id(handler_input)
        user_info = config.resolve_user(person_id=person_id)

        linea = config.clean_alphanumeric_code(linea_slot.value) if linea_slot and linea_slot.value else user_info["service"]

        if paradero_slot and paradero_slot.value:
            paradero = config.clean_alphanumeric_code(paradero_slot.value)
            speak_output = red_service.format_prediction_speech(paradero, linea)
        else:
            coords_info = location_service.get_coordinates_from_request(handler_input)
            if coords_info:
                lat, lon, source = coords_info
                nearest = location_service.find_nearest_stop(lat, lon)
                if nearest:
                    speak_output = red_service.format_prediction_speech(
                        nearest["code"], linea, distance_to_stop=nearest["distance_meters"]
                    )
                else:
                    user_stops = config.get_user_stops(person_id=person_id)
                    sentido_val = sentido_slot.value if sentido_slot and sentido_slot.value else None
                    speak_output = red_service.format_dual_prediction_speech(
                        linea=linea,
                        stop_ida=user_stops["ida"],
                        stop_vuelta=user_stops.get("vuelta"),
                        intersection=user_stops.get("intersection"),
                        sentido_query=sentido_val
                    )
            else:
                user_stops = config.get_user_stops(person_id=person_id)
                sentido_val = sentido_slot.value if sentido_slot and sentido_slot.value else None
                speak_output = red_service.format_dual_prediction_speech(
                    linea=linea,
                    stop_ida=user_stops["ida"],
                    stop_vuelta=user_stops.get("vuelta"),
                    intersection=user_stops.get("intersection"),
                    sentido_query=sentido_val
                )

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
        linea = config.clean_alphanumeric_code(linea_slot.value) if linea_slot and linea_slot.value else config.DEFAULT_SERVICE

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


class RouteToDestinationIntentHandler(AbstractRequestHandler):
    """Maneja la consulta de cómo llegar a un destino o qué micros sirven."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("RouteToDestinationIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        slots = handler_input.request_envelope.request.intent.slots or {}
        dest_slot = slots.get("Destination")
        dest_value = dest_slot.value if dest_slot and dest_slot.value else None

        if not dest_value or not dest_value.strip():
            speech = "Por favor dime a qué dirección, esquina o lugar quieres ir."
            return (
                handler_input.response_builder
                .speak(speech)
                .ask("¿A dónde deseas ir?")
                .response
            )

        # 1. Resolver destino a coordenadas
        norm_dest = normalize_destination_query(dest_value)
        dest_coords = geocode_address(norm_dest)
        if not dest_coords:
            # Reintentar sin normalización adicional por si es un hito directo
            dest_coords = geocode_address(dest_value)

        if not dest_coords:
            speech = (
                f"No pude encontrar la dirección o esquina {dest_value}. "
                "Por favor intenta diciendo la calle principal y una intersección, por ejemplo: Providencia con Pedro de Valdivia."
            )
            return handler_input.response_builder.speak(speech).response

        dest_lat, dest_lon = dest_coords

        # 2. Resolver origen (explícito o automático)
        orig_slot = slots.get("Origin")
        orig_value = orig_slot.value if orig_slot and orig_slot.value else None
        orig_coords = None

        if orig_value:
            norm_orig = normalize_destination_query(orig_value)
            orig_coords = geocode_address(norm_orig) or geocode_address(orig_value)

        if not orig_coords:
            # Obtener desde GPS / Device Address o paradero guardado
            coords_info = None
            try:
                coords_info = get_coordinates_from_request(handler_input)
            except Exception:
                coords_info = None

            if coords_info:
                orig_coords = (coords_info[0], coords_info[1])
            else:
                person_id = _extract_person_id(handler_input)
                user_id = None
                try:
                    user_id = handler_input.request_envelope.context.system.user.user_id
                except Exception:
                    pass

                user_stops = config.get_user_stops(user_key_or_name=user_id, person_id=person_id)
                ida_stop = user_stops.get("ida") if isinstance(user_stops, dict) else None
                vuelta_stop = user_stops.get("vuelta") if isinstance(user_stops, dict) else None
                stop_code = (
                    (ida_stop.get("code") if isinstance(ida_stop, dict) else ida_stop)
                    or (vuelta_stop.get("code") if isinstance(vuelta_stop, dict) else vuelta_stop)
                    or config.DEFAULT_STOP_CODE
                )

                # Buscar lat/lon del paradero en stops.db
                row = None
                if os.path.exists(location_service.DB_PATH):
                    try:
                        conn = sqlite3.connect(location_service.DB_PATH)
                        c = conn.cursor()
                        c.execute("SELECT lat, lon FROM stops WHERE code = ?", (stop_code,))
                        row = c.fetchone()
                        conn.close()
                    except Exception as e:
                        logger.warning(f"Error consultando paradero {stop_code} en DB: {e}")

                if row:
                    orig_coords = (row[0], row[1])
                else:
                    orig_coords = (-33.4578, -70.5891)  # Fallback centro/origen

        # 3. Construir respuesta hablada
        speech = format_route_speech(dest_value, orig_coords[0], orig_coords[1], dest_lat, dest_lon)
        return handler_input.response_builder.speak(speech).response


class WatchBusIntentHandler(AbstractRequestHandler):
    """Handler para vigilar una micro y enviar un recordatorio cuando esté cerca."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("WatchBusIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        # 1. Verificar permisos de recordatorios
        if not reminders_service.has_reminder_permission(handler_input):
            speak_output = (
                "Para avisarte cuando venga tu micro, necesito que actives el permiso de recordatorios en tu aplicación de Alexa. "
                "Te he enviado una tarjeta a tu app para activarlo fácilmente con un toque."
            )
            return (
                handler_input.response_builder
                .speak(speak_output)
                .set_card(AskForPermissionsConsentCard(permissions=["alexa::alerts:reminders:skill:readwrite"]))
                .response
            )

        # 2. Extraer slots
        slots = handler_input.request_envelope.request.intent.slots or {}
        linea_slot = slots.get("linea")
        tiempo_slot = slots.get("tiempo")

        person_id = _extract_person_id(handler_input)
        user_id = None
        try:
            user_id = handler_input.request_envelope.context.system.user.user_id
        except Exception:
            user_id = person_id or "default_user"

        # Resolver línea
        linea = linea_slot.value if linea_slot and linea_slot.value else None
        if not linea:
            linea = config.get_user_line(user_key_or_name=user_id, person_id=person_id)
        if not linea:
            linea = "513"  # Valor predeterminado

        clean_linea = config.clean_alphanumeric_code(linea)

        # Resolver umbral de minutos (default 5 min)
        threshold_minutes = 5
        if tiempo_slot and tiempo_slot.value:
            try:
                threshold_minutes = max(1, int(tiempo_slot.value))
            except ValueError:
                threshold_minutes = 5

        # Resolver paradero y esquina
        user_stops = config.get_user_stops(user_key_or_name=user_id, person_id=person_id)
        ida_stop = user_stops.get("ida") if isinstance(user_stops, dict) else None
        vuelta_stop = user_stops.get("vuelta") if isinstance(user_stops, dict) else None
        intersection = user_stops.get("intersection") if isinstance(user_stops, dict) else None

        stop_info = ida_stop or vuelta_stop
        stop_code = (
            (stop_info.get("code") if isinstance(stop_info, dict) else stop_info)
            or config.DEFAULT_STOP_CODE
        )
        corner_name = intersection or (stop_info.get("name") if isinstance(stop_info, dict) else stop_code)

        # 3. Comprobar predictivo actual: si ya viene cerca, avisar de inmediato
        try:
            pred = red_service.get_stop_predictions(stop_code, clean_linea)
            if pred.get("success") and pred.get("buses"):
                min_time = pred["buses"][0].get("min_time", 0)
                if min_time <= threshold_minutes:
                    speak_output = (
                        f"Tu micro {clean_linea} ya está muy cerca, a {min_time} minutos de tu esquina "
                        f"en {corner_name}. Es momento de salir ahora mismo."
                    )
                    return handler_input.response_builder.speak(speak_output).response
        except Exception as e:
            logger.warning(f"Error consultando predictivo inicial en WatchBusIntent: {e}")

        # 4. Iniciar vigilancia en segundo plano
        system = handler_input.request_envelope.context.system
        api_endpoint = getattr(system, "api_endpoint", None) or "https://api.amazonalexa.com"
        api_access_token = getattr(system, "api_access_token", None) or ""

        watcher_manager.start_watch(
            user_id=user_id,
            linea=clean_linea,
            stop_code=stop_code,
            corner_name=corner_name,
            threshold_minutes=threshold_minutes,
            api_endpoint=api_endpoint,
            api_access_token=api_access_token
        )

        speak_output = (
            f"Perfecto, estaré vigilando la micro {clean_linea} en tu esquina de {corner_name}. "
            f"Te avisaré apenas esté a {threshold_minutes} minutos."
        )
        return handler_input.response_builder.speak(speak_output).response


class CancelWatchIntentHandler(AbstractRequestHandler):
    """Handler para cancelar la vigilancia activa de micros."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("CancelWatchIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        person_id = _extract_person_id(handler_input)
        user_id = None
        try:
            user_id = handler_input.request_envelope.context.system.user.user_id
        except Exception:
            user_id = person_id or "default_user"

        cancelled = watcher_manager.cancel_watch(user_id)
        if cancelled:
            speak_output = "Listo, cancelé la vigilancia de tu micro."
        else:
            speak_output = "No tienes ninguna vigilancia de micro activa en este momento."

        return handler_input.response_builder.speak(speak_output).response


class HelpIntentHandler(AbstractRequestHandler):
    """Handler para ayuda estándar de Alexa."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        speak_output = (
            "Puedes decir: cuánto saldo le queda a mi Bip, cuánto le falta a la 513 de ida o de vuelta, "
            "preguntar: ¿alcanzo a salir?, o configurar tu esquina diciendo: mi esquina es Grecia con Salvador."
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

        try:
            from src import observability
            req_attrs = handler_input.attributes_manager.request_attributes
            observability.store.record(
                request_type=req_attrs.get("_request_type", "Error"),
                intent_name=req_attrs.get("_intent_name"),
                slots=req_attrs.get("_slots"),
                user_id=req_attrs.get("_user_id"),
                speech=speak_output,
                status="error",
                error_detail=str(exception)
            )
        except Exception as e:
            logger.warning(f"Error registrando observabilidad de excepción: {e}")

        return (
            handler_input.response_builder
            .speak(speak_output)
            .ask("¿Quieres intentar de nuevo?")
            .response
        )
