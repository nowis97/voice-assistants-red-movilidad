import sqlite3
import os
import math
import logging
import requests
import urllib.parse
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)

# Ruta a la base de datos de paraderos de Santiago
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "stops.db")

# Cache en memoria para geocodificación de direcciones de dispositivos Echo
_ADDRESS_GEO_CACHE: Dict[str, Tuple[float, float]] = {}


def find_nearest_stop(lat: float, lon: float, max_radius_meters: int = 1500) -> Optional[Dict[str, Any]]:
    """
    Busca el paradero de Red Movilidad más cercano a un par de coordenadas (lat, lon)
    utilizando la base de datos local SQLite en menos de 2 milisegundos.
    """
    if not os.path.exists(DB_PATH):
        logger.warning(f"stops.db no encontrado en {DB_PATH}")
        return None

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Aproximación rápida euclidiana para ordenar
        # 1 grado de latitud ~ 111.000 metros; 1 grado de longitud en Santiago (~-33°) ~ 93.000 metros
        lat_scale = 1.0
        lon_scale = math.cos(math.radians(lat))

        c.execute("""
            SELECT code, name, lat, lon,
                   ((lat - ?) * (lat - ?) + (lon - ?) * (lon - ?) * ? * ?) as dist_metric
            FROM stops
            WHERE lat BETWEEN ? AND ?
              AND lon BETWEEN ? AND ?
            ORDER BY dist_metric ASC
            LIMIT 1
        """, (
            lat, lat, lon, lon, lon_scale, lon_scale,
            lat - 0.02, lat + 0.02,
            lon - 0.02, lon + 0.02
        ))

        row = c.fetchone()
        conn.close()

        if not row:
            return None

        code, name, s_lat, s_lon, _ = row

        # Calcular distancia real en metros (fórmula Haversine)
        dlat = math.radians(s_lat - lat)
        dlon = math.radians(s_lon - lon)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat)) * math.cos(math.radians(s_lat)) *
             math.sin(dlon / 2) ** 2)
        c_dist = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        meters = int(6371000 * c_dist)

        if meters > max_radius_meters:
            logger.info(f"Paradero más cercano {code} está a {meters}m (mayor al radio {max_radius_meters}m)")
            return None

        # Limpiar nombre (en GTFS viene ej: "PA345-Parada 4 / ...")
        clean_name = name
        if "-" in clean_name and clean_name.startswith(code):
            clean_name = clean_name.split("-", 1)[1].strip()

        return {
            "code": code,
            "name": clean_name,
            "latitude": s_lat,
            "longitude": s_lon,
            "distance_meters": meters
        }
    except Exception as e:
        logger.error(f"Error consultando paradero más cercano: {e}", exc_info=True)
        return None


def geocode_address(address_line: str, city: str = "Santiago", country: str = "Chile") -> Optional[Tuple[float, float]]:
    """
    Convierte una dirección postal de Amazon Alexa en coordenadas (lat, lon)
    vía OpenStreetMap Nominatim. Usa caché en memoria.
    """
    cache_key = f"{address_line.strip().lower()}, {city.strip().lower()}"
    if cache_key in _ADDRESS_GEO_CACHE:
        return _ADDRESS_GEO_CACHE[cache_key]

    query = f"{address_line}, {city}, {country}"
    url = "https://nominatim.openstreetmap.org/search?q=" + urllib.parse.quote(query) + "&format=json&limit=1"

    try:
        resp = requests.get(url, headers={"User-Agent": "AlexaRedMovilidad/1.0"}, timeout=4)
        if resp.status_code == 200:
            data = resp.json()
            if data and len(data) > 0:
                lat = float(data[0]["lat"])
                lon = float(data[0]["lon"])
                _ADDRESS_GEO_CACHE[cache_key] = (lat, lon)
                logger.info(f"Geocodificado exitoso '{cache_key}' -> ({lat}, {lon})")
                return (lat, lon)
    except Exception as e:
        logger.warning(f"Fallo al geocodificar dirección '{query}': {e}")

    return None


def get_coordinates_from_request(handler_input: Any) -> Optional[Tuple[float, float, str]]:
    """
    Intenta extraer coordenadas de:
    1. Geolocation API (móvil / app Alexa en el teléfono con GPS activo)
    2. Device Address API (parlante Echo fijo en el hogar)
    Retorna (lat, lon, fuente) o None.
    """
    context = handler_input.request_envelope.context

    # 1. Intentar Geolocation (Móvil)
    geo = getattr(context, "geolocation", None)
    if geo and getattr(geo, "coordinate", None):
        coord = geo.coordinate
        lat = getattr(coord, "latitude_in_degrees", None)
        lon = getattr(coord, "longitude_in_degrees", None)
        if lat is not None and lon is not None:
            logger.info(f"Ubicación GPS móvil detectada: ({lat}, {lon})")
            return (lat, lon, "gps")

    # 2. Intentar Device Address API (Echo fijo)
    system = getattr(context, "system", None)
    if not system:
        return None

    device = getattr(system, "device", None)
    device_id = getattr(device, "device_id", None) if device else None
    api_endpoint = getattr(system, "api_endpoint", None)
    api_token = getattr(system, "api_access_token", None)

    if not device_id or not api_endpoint or not api_token:
        return None

    address_url = f"{api_endpoint}/v1/devices/{device_id}/settings/address"
    headers = {"Authorization": f"Bearer {api_token}"}

    try:
        resp = requests.get(address_url, headers=headers, timeout=3)
        if resp.status_code == 200:
            addr = resp.json()
            line1 = addr.get("addressLine1") or addr.get("addressLine2") or ""
            city = addr.get("city") or addr.get("districtOrCounty") or "Santiago"
            if line1:
                coords = geocode_address(line1, city)
                if coords:
                    return (coords[0], coords[1], "device_address")
        elif resp.status_code == 403:
            logger.info("Permiso de Device Address no concedido por el usuario")
    except Exception as e:
        logger.warning(f"Error consultando Device Address API: {e}")

    return None


def resolve_stop_for_request(handler_input: Any, fallback_stop: str = "PA345") -> Tuple[str, str, Optional[int]]:
    """
    Resuelve el mejor código de paradero:
    1. Busca por ubicación (GPS o dirección del Echo).
    2. Si falla o no hay permisos, usa el paradero favorito/fallback.
    Retorna (stop_code, stop_name, distance_meters).
    """
    coords_info = get_coordinates_from_request(handler_input)
    if coords_info:
        lat, lon, source = coords_info
        nearest = find_nearest_stop(lat, lon)
        if nearest:
            logger.info(f"Paradero resuelto por {source}: {nearest['code']} ({nearest['distance_meters']}m)")
            return (nearest["code"], nearest["name"], nearest["distance_meters"])

    return (fallback_stop, "paradero habitual", None)
