import logging
import requests
from typing import Optional, Dict, Any, List
import config

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

def format_balance_speech(bip_code: Optional[str] = None) -> str:
    """Construye la frase hablada para el saldo de la tarjeta Bip!."""
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

    return f"Tu tarjeta Bip tiene un saldo de {balance} pesos.{alerta}"


def format_prediction_speech(stop_code: Optional[str] = None, service: Optional[str] = None) -> str:
    """Construye la frase hablada para el tiempo de llegada de la micro."""
    res = get_stop_predictions(stop_code, service)
    if not res["success"]:
        return res.get("error", "No pude obtener información del paradero.")

    buses = res["buses"]
    stop_name = res["stop_name"]
    target = res.get("target_service")

    if not buses:
        if target:
            return f"No hay buses del recorrido {target} dirigiéndose al paradero {res['stop_code']} en este momento."
        return f"No hay buses en camino para el paradero {res['stop_code']} en este momento."

    # Tomar el bus más próximo
    first = buses[0]
    linea = first["service"]
    min_t = first["min_time"]
    max_t = first["max_time"]
    meters = first["meters"]

    if max_t <= 1 or meters <= 100:
        tiempo_texto = "está llegando ahora mismo"
    elif min_t == max_t or min_t == 0:
        tiempo_texto = f"le faltan unos {max_t} minutos"
    else:
        tiempo_texto = f"le faltan entre {min_t} y {max_t} minutos"

    distancia_texto = f"a {meters} metros" if meters > 0 else "en el paradero"

    speech = f"La micro {linea} {tiempo_texto}, viene {distancia_texto}."

    # Si hay un segundo bus de la misma línea o en general
    if len(buses) > 1 and target:
        second = buses[1]
        speech += f" El siguiente bus viene a {second['meters']} metros."
    elif len(buses) > 1 and not target:
        second = buses[1]
        speech += f" También la {second['service']} viene a unos {second['max_time']} minutos."

    return speech


def format_travel_summary_speech() -> str:
    """
    Comando combinado: "¿Alcanzo a salir?"
    Consulta en simultáneo el saldo y la micro habitual.
    """
    bal_res = get_bip_balance()
    pred_res = get_stop_predictions(config.DEFAULT_STOP_CODE, config.DEFAULT_SERVICE)

    parts = []

    # Micro
    if pred_res["success"] and pred_res["buses"]:
        first = pred_res["buses"][0]
        m = first["meters"]
        t = first["max_time"]
        if t <= 2:
            parts.append(f"La {config.DEFAULT_SERVICE} ya está llegando a {m} metros.")
        else:
            parts.append(f"La {config.DEFAULT_SERVICE} viene a {m} metros, le faltan unos {t} minutos.")
    else:
        parts.append(f"No veo buses de la {config.DEFAULT_SERVICE} próximos a tu paradero habitual.")

    # Saldo
    if bal_res["success"]:
        parts.append(f"Tu saldo Bip es de {bal_res['balance']} pesos.")

    return " ".join(parts)
