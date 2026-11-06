import logging
import requests
from typing import Optional, Dict, Any, List
import config

try:
    from src.location_service import clean_intersection_name
except ImportError:
    try:
        from location_service import clean_intersection_name
    except ImportError:
        def clean_intersection_name(name: str) -> str:
            return name

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 8


def get_bip_balance(bip_code: Optional[str] = None) -> Dict[str, Any]:
    """
    Consulta el saldo de una tarjeta Bip! física utilizando el endpoint oficial
    reverso de la aplicación Red Movilidad.
    """
    card_number = (bip_code or config.DEFAULT_BIP_NUMBER).strip()
    if not card_number or not card_number.isdigit():
        return {
            "success": False,
            "error": "Número de tarjeta Bip! no válido.",
            "balance": None
        }

    url = f"https://appred.tstgo.cl/phone/v13/payment/balance?bip_code={card_number}"

    try:
        response = requests.get(url, headers=config.RED_HEADERS, timeout=TIMEOUT_SECONDS)
        if response.status_code == 200:
            data = response.json()
            balance = data.get("cardBalance", 0)
            benefit = data.get("benefitInfo", {})
            return {
                "success": True,
                "card_number": card_number,
                "balance": balance,
                "formatted_balance": f"${balance:,}".replace(",", "."),
                "benefit_active": benefit.get("isActive", False),
                "raw": data
            }
        else:
            logger.warning("Error consultando saldo: HTTP %s", response.status_code)
            return {
                "success": False,
                "error": f"El servicio de Bip respondió con error HTTP {response.status_code}.",
                "balance": None
            }
    except requests.RequestException as e:
        logger.error("Fallo de red al consultar saldo Bip: %s", e)
        return {
            "success": False,
            "error": "No fue posible conectar con el servidor de Red Movilidad.",
            "balance": None
        }


def get_stop_predictions(stop_code: Optional[str] = None, service: Optional[str] = None) -> Dict[str, Any]:
    """
    Consulta el tiempo estimado de llegada y la distancia de los buses a un paradero específico.
    Utiliza el predictivo en tiempo real conectado al DTPM / Transantiago.
    """
    clean_stop = (stop_code or config.DEFAULT_STOP_CODE).strip().upper()
    target_service = service.strip().upper() if service else None

    url = f"https://api.xor.cl/red/bus-stop/{clean_stop}"

    try:
        response = requests.get(url, headers={"User-Agent": "AlexaRedMovilidad/1.0"}, timeout=TIMEOUT_SECONDS)
        if response.status_code == 200:
            data = response.json()
            stop_name = data.get("name", clean_stop)
            all_services = data.get("services", [])

            matching_buses = []
            for s in all_services:
                s_id = s.get("id", "").strip().upper()
                if target_service and s_id != target_service:
                    continue

                if not s.get("valid", False):
                    continue

                for bus in s.get("buses", []):
                    matching_buses.append({
                        "service": s_id,
                        "license_plate": bus.get("id", ""),
                        "meters": bus.get("meters_distance", 0),
                        "min_time": bus.get("min_arrival_time", 0),
                        "max_time": bus.get("max_arrival_time", 0),
                    })

            # Ordenar buses por tiempo mínimo de llegada
            matching_buses.sort(key=lambda b: (b["min_time"], b["meters"]))

            return {
                "success": True,
                "stop_code": clean_stop,
                "stop_name": stop_name,
                "target_service": target_service,
                "buses": matching_buses,
                "raw_services_count": len(all_services)
            }
        elif response.status_code == 404:
            return {
                "success": False,
                "error": f"El paradero {clean_stop} no fue encontrado.",
                "buses": []
            }
        else:
            return {
                "success": False,
                "error": f"Error del servicio predictivo (HTTP {response.status_code}).",
                "buses": []
            }
    except requests.RequestException as e:
        logger.error("Fallo de red al consultar paradero %s: %s", clean_stop, e)
        return {
            "success": False,
            "error": "No fue posible conectar con el servicio de información de paradas.",
            "buses": []
        }


def get_buses_on_route(route: str) -> List[Dict[str, Any]]:
    """
    Obtiene la telemetría GPS en tiempo real de todos los buses activos en una ruta/recorrido
    directamente desde el backend telemático de Red Movilidad.
    """
    clean_route = route.strip().upper()
    url = f"https://appred.tstgo.cl/phone/v13/onlinegps/busesOnRoute?route={clean_route}"

    try:
        response = requests.get(url, headers=config.RED_HEADERS, timeout=TIMEOUT_SECONDS)
        if response.status_code == 200:
            data = response.json()
            return data.get("active_buses", [])
    except requests.RequestException as e:
        logger.error("Fallo al obtener buses en ruta %s: %s", clean_route, e)

    return []


# -------------------------------------------------------------------------
# Constructores de lenguaje natural (Texto para Alexa)
# -------------------------------------------------------------------------

def format_balance_speech(bip_code: Optional[str] = None, user_name: Optional[str] = None) -> str:
    """Construye la frase hablada para el saldo de la tarjeta Bip!, personalizable por usuario."""
    res = get_bip_balance(bip_code)
    if not res["success"]:
        return res.get("error", "No pude consultar el saldo de tu tarjeta en este momento.")

    balance = res["balance"]
    if balance < 800:
        alerta = " Ojo, te queda menos de un pasaje, recuerda recargar."
    elif balance < 1700:
        alerta = " Te alcanza justo para uno o dos viajes."
    else:
        alerta = ""

    saludo = f"{user_name}, tu" if user_name else "Tu"
    return f"{saludo} tarjeta Bip tiene un saldo de {balance} pesos.{alerta}"


def _format_single_bus_arrival(bus: Dict[str, Any]) -> str:
    """Helper interno para describir llegada de un bus."""
    max_t = bus.get("max_time", 0)
    min_t = bus.get("min_time", 0)
    meters = bus.get("meters", 0)

    if max_t <= 1 or meters <= 100:
        return "está llegando ahora mismo"
    elif min_t == max_t or min_t == 0:
        return f"le faltan unos {max_t} minutos"
    else:
        return f"le faltan entre {min_t} y {max_t} minutos"


def format_prediction_speech(
    stop_code: Optional[str] = None,
    service: Optional[str] = None,
    distance_to_stop: Optional[int] = None
) -> str:
    """Construye la frase hablada para el tiempo de llegada de la micro."""
    res = get_stop_predictions(stop_code, service)
    if not res["success"]:
        return res.get("error", "No pude obtener información del paradero.")

    buses = res["buses"]
    stop_name = res["stop_name"]
    target = res.get("target_service")

    prefijo = ""
    if distance_to_stop is not None:
        prefijo = f"Para tu paradero más cercano a {distance_to_stop} metros: "

    if not buses:
        if target:
            return f"{prefijo}No hay buses del recorrido {target} dirigiéndose al paradero {res['stop_code']} en este momento."
        return f"{prefijo}No hay buses en camino para el paradero {res['stop_code']} en este momento."

    # Tomar el bus más próximo
    first = buses[0]
    linea = first["service"]
    meters = first["meters"]
    tiempo_texto = _format_single_bus_arrival(first)

    distancia_texto = f"a {meters} metros" if meters > 0 else "en el paradero"

    speech = f"{prefijo}La micro {linea} {tiempo_texto}, viene {distancia_texto}."

    # Si hay un segundo bus de la misma línea o en general
    if len(buses) > 1 and target:
        second = buses[1]
        speech += f" El siguiente bus viene a {second['meters']} metros."
    elif len(buses) > 1 and not target:
        second = buses[1]
        speech += f" También la {second['service']} viene a unos {second['max_time']} minutos."

    return speech


def format_dual_prediction_speech(
    linea: str,
    stop_ida: Dict[str, Any],
    stop_vuelta: Optional[Dict[str, Any]] = None,
    intersection: Optional[str] = None,
    sentido_query: Optional[str] = None
) -> str:
    """
    Construye la respuesta hablada de predicción para un recorrido en la esquina del usuario,
    reportando ambos paraderos enfrentados o discriminando si el usuario pidió un sentido específico.
    """
    code_ida = stop_ida.get("code")
    code_vuelta = stop_vuelta.get("code") if stop_vuelta else None
    raw_corner = intersection or stop_ida.get("name", "tu esquina")
    corner = clean_intersection_name(raw_corner) if (raw_corner and raw_corner != "tu esquina") else raw_corner

    # Si el usuario consultó un sentido específico (ej: "de ida", "hacia el centro", "vuelta", "regreso")
    if sentido_query:
        norm_sentido = sentido_query.lower()
        es_vuelta = any(w in norm_sentido for w in ["vuelta", "regreso", "casa", "peñalolén", "barrio"])
        target_stop = stop_vuelta if (es_vuelta and stop_vuelta) else stop_ida
        label_sentido = "de vuelta" if (es_vuelta and stop_vuelta) else "de ida"

        res = get_stop_predictions(target_stop.get("code"), linea)
        if not res["success"]:
            return f"No pude consultar la {linea} {label_sentido} en el paradero {target_stop.get('code')}."

        buses = res.get("buses", [])
        if not buses:
            return f"No vienen micros de la {linea} {label_sentido} acercándose al paradero {target_stop.get('code')} en {corner}."

        first = buses[0]
        arrival_str = _format_single_bus_arrival(first)
        dist_str = f"a {first['meters']} metros" if first.get("meters") else "en camino"
        return f"La {linea} {label_sentido} viene en {corner} (paradero {target_stop.get('code')}) {dist_str}, {arrival_str}."

    # Consulta general sin sentido especificado: consultar ambos paraderos
    res_ida = get_stop_predictions(code_ida, linea)
    res_vuelta = get_stop_predictions(code_vuelta, linea) if (code_vuelta and code_vuelta != code_ida) else None

    buses_ida = res_ida.get("buses", []) if res_ida.get("success") else []
    buses_vuelta = res_vuelta.get("buses", []) if (res_vuelta and res_vuelta.get("success")) else []

    if not buses_ida and not buses_vuelta:
        return f"No hay buses del recorrido {linea} aproximándose a tu esquina {corner} en este momento."

    parts = [f"Para la {linea} en {corner}:"]

    if buses_ida:
        first_ida = buses_ida[0]
        arr_ida = _format_single_bus_arrival(first_ida)
        parts.append(f"de ida en el paradero {code_ida} {arr_ida};")
    else:
        parts.append(f"de ida en el paradero {code_ida} no vienen buses;")

    if code_vuelta and code_vuelta != code_ida:
        if buses_vuelta:
            first_v = buses_vuelta[0]
            arr_v = _format_single_bus_arrival(first_v)
            parts.append(f"y en la vereda del frente (paradero {code_vuelta}) {arr_v}.")
        else:
            parts.append(f"y en la vereda del frente (paradero {code_vuelta}) no vienen buses próximos.")
    elif not buses_ida:
        return f"No veo micros de la {linea} en camino al paradero {code_ida}."
    else:
        parts[-1] = parts[-1].rstrip(";") + "."

    return " ".join(parts)


def format_travel_summary_speech(
    user_name: Optional[str] = None,
    card_number: Optional[str] = None,
    stop_code: Optional[str] = None,
    service: Optional[str] = None,
    distance_to_stop: Optional[int] = None
) -> str:
    """
    Comando combinado: "¿Alcanzo a salir?"
    Consulta en simultáneo el saldo de la persona y su micro más próxima.
    """
    target_stop = stop_code or config.DEFAULT_STOP_CODE
    target_service = service or config.DEFAULT_SERVICE
    target_card = card_number or config.DEFAULT_BIP_NUMBER

    bal_res = get_bip_balance(target_card)
    pred_res = get_stop_predictions(target_stop, target_service)

    parts = []

    # Saludo personalizado si se reconoce al usuario
    if user_name:
        parts.append(f"{user_name},")

    # Micro
    loc_detail = f" a {distance_to_stop} metros" if distance_to_stop else ""
    if pred_res["success"] and pred_res["buses"]:
        first = pred_res["buses"][0]
        m = first["meters"]
        t = first["max_time"]
        if t <= 2:
            parts.append(f"la {target_service} para tu paradero{loc_detail} ya está llegando a {m} metros.")
        else:
            parts.append(f"la {target_service} para tu paradero{loc_detail} viene a {m} metros, le faltan unos {t} minutos.")
    else:
        parts.append(f"no veo buses de la {target_service} próximos a tu paradero{loc_detail}.")

    # Saldo
    if bal_res["success"]:
        parts.append(f"Tu saldo Bip es de {bal_res['balance']} pesos.")

    return " ".join(parts)


def plan_trip(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float
) -> Dict[str, Any]:
    """
    Consulta el planificador multimodal oficial de Red Movilidad para obtener rutas óptimas
    entre dos coordenadas de Santiago.
    """
    url = "https://appred.tstgo.cl/phone/v13/routeplanner/calculate"
    params = {
        "origin": f"{origin_lat},{origin_lon}",
        "destination": f"{dest_lat},{dest_lon}"
    }

    try:
        response = requests.get(url, headers=config.RED_HEADERS, params=params, timeout=TIMEOUT_SECONDS)
        if response.status_code != 200:
            logger.warning(f"Error del planificador Red Movilidad: HTTP {response.status_code}")
            return {
                "success": False,
                "error": f"Error del planificador de Red (HTTP {response.status_code}).",
                "direct_routes": [],
                "transfer_routes": [],
                "total_itineraries": 0
            }

        data = response.json()
        if not isinstance(data, list):
            return {
                "success": False,
                "error": "Respuesta inesperada del servicio de rutas.",
                "direct_routes": [],
                "transfer_routes": [],
                "total_itineraries": 0
            }

        direct_routes = []
        transfer_routes = []

        for itin in data:
            duration_min = round(itin.get("duration", 0) / 60)
            transfers = itin.get("transfers", 0)
            legs = itin.get("legs", [])

            transit_legs = [l for l in legs if l.get("mode") in ("BUS", "SUBWAY")]
            walk_legs = [l for l in legs if l.get("mode") == "WALK"]

            first_walk = walk_legs[0].get("distance", 0) if walk_legs else 0

            if transfers == 0 and transit_legs:
                t_leg = transit_legs[0]
                from_data = t_leg.get("from", {})
                to_data = t_leg.get("to", {})
                direct_routes.append({
                    "mode": t_leg.get("mode"),
                    "route": t_leg.get("route"),
                    "from_stop_id": from_data.get("stopId", ""),
                    "from_stop_name": clean_intersection_name(from_data.get("name", "")),
                    "to_stop_id": to_data.get("stopId", ""),
                    "to_stop_name": clean_intersection_name(to_data.get("name", "")),
                    "walk_distance_meters": int(first_walk),
                    "duration_minutes": duration_min
                })
            elif transfers >= 1 and len(transit_legs) >= 2:
                leg1 = transit_legs[0]
                leg2 = transit_legs[1]
                from1 = leg1.get("from", {})
                to1 = leg1.get("to", {})
                to2 = leg2.get("to", {})
                transfer_routes.append({
                    "first_mode": leg1.get("mode"),
                    "first_route": leg1.get("route"),
                    "first_stop_id": from1.get("stopId", ""),
                    "first_stop_name": clean_intersection_name(from1.get("name", "")),
                    "transfer_point": clean_intersection_name(to1.get("name", "")),
                    "second_mode": leg2.get("mode"),
                    "second_route": leg2.get("route"),
                    "destination_stop_name": clean_intersection_name(to2.get("name", "")),
                    "walk_distance_meters": int(first_walk),
                    "duration_minutes": duration_min,
                    "transfers": transfers
                })

        return {
            "success": True,
            "direct_routes": direct_routes,
            "transfer_routes": transfer_routes,
            "total_itineraries": len(data)
        }
    except requests.RequestException as e:
        logger.error(f"Fallo de conexión al planificador Red: {e}")
        return {
            "success": False,
            "error": "No fue posible conectar con el planificador de rutas de Red Movilidad.",
            "direct_routes": [],
            "transfer_routes": [],
            "total_itineraries": 0
        }

