import sqlite3
import os
import math
import logging
import requests
import urllib.parse
import re
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


def clean_intersection_name(raw_name: str) -> str:
    """
    Transforma un nombre técnico GTFS de paradero en una frase hablada natural.
    Ejemplos:
      'PC186-Avenida Apoquindo / Esq. El Bosque Norte' -> 'Avenida Apoquindo con El Bosque Norte'
      'PD184-Av. Grecia / Esq. Salvador' -> 'Avenida Grecia con Salvador'
      'PA345-Parada 4 / (M) Universidad De Chile' -> 'Parada 4 con Metro Universidad De Chile'
    """
    if not raw_name:
        return ""

    # 1. Eliminar prefijo de código (ej: 'PC186-', 'PA345 - ')
    s = re.sub(r"^[A-Z0-9]+[-\s]+", "", raw_name.strip())

    # 2. Expandir indicador de Metro
    s = re.sub(r"\(M\)", "Metro", s)

    # 3. Expandir abreviaturas comunes de vías
    s = re.sub(r"\bAv\.\s*", "Avenida ", s, flags=re.IGNORECASE)
    s = re.sub(r"\bPque\.\s*", "Parque ", s, flags=re.IGNORECASE)
    s = re.sub(r"\bPje\.\s*", "Pasaje ", s, flags=re.IGNORECASE)

    # 4. Normalizar intersección (/ Esq. o / por 'con')
    s = re.sub(r"/\s*(?:Esq\.?|esq\.?)?\s*", " con ", s)

    # 5. Limpieza de espacios redundantes
    s = re.sub(r"\s+", " ", s).strip()
    return s


def find_opposing_stop(stop_code: str, max_meters: int = 250) -> Optional[Dict[str, Any]]:
    """
    Encuentra el paradero enfrentado en la vereda contraria para un código dado,
    buscando en stops.db por proximidad geográfica (<250m) en el mismo eje vial.
    """
    if not os.path.exists(DB_PATH) or not stop_code:
        return None

    clean_code = stop_code.strip().upper()
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Obtener datos del paradero origen
        c.execute("SELECT code, name, lat, lon FROM stops WHERE code = ?", (clean_code,))
        origin = c.fetchone()
        if not origin:
            conn.close()
            return None

        _, origin_name, o_lat, o_lon = origin

        # Extraer eje principal (antes de 'con' o '/')
        cleaned_origin = clean_intersection_name(origin_name)
        main_axis = cleaned_origin.split(" con ")[0].strip() if " con " in cleaned_origin else cleaned_origin

        # Buscar paraderos cercanos dentro de un radio de ~250m (~0.0025 grados)
        c.execute("""
            SELECT code, name, lat, lon
            FROM stops
            WHERE code != ?
              AND lat BETWEEN ? AND ?
              AND lon BETWEEN ? AND ?
        """, (clean_code, o_lat - 0.0025, o_lat + 0.0025, o_lon - 0.0025, o_lon + 0.0025))

        candidates = c.fetchall()
        conn.close()

        best_stop = None
        min_dist = float("inf")

        for c_code, c_name, c_lat, c_lon in candidates:
            # Calcular distancia Haversine
            dlat = math.radians(c_lat - o_lat)
            dlon = math.radians(c_lon - o_lon)
            a = (math.sin(dlat / 2) ** 2 +
                 math.cos(math.radians(o_lat)) * math.cos(math.radians(c_lat)) *
                 math.sin(dlon / 2) ** 2)
            dist_m = int(6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

            if dist_m > max_meters:
                continue

            cleaned_cand = clean_intersection_name(c_name)
            # Priorizar paraderos que compartan el mismo eje vial
            axis_match = (main_axis.lower() in cleaned_cand.lower() or
                          ("metro" in cleaned_origin.lower() and "metro" in cleaned_cand.lower()))

            if axis_match and dist_m < min_dist:
                min_dist = dist_m
                best_stop = {
                    "code": c_code,
                    "name": cleaned_cand,
                    "latitude": c_lat,
                    "longitude": c_lon,
                    "distance_meters": dist_m
                }

        return best_stop
    except Exception as e:
        logger.error(f"Error buscando paradero opuesto a {stop_code}: {e}", exc_info=True)
        return None


def find_stops_by_intersection(street1: str, street2: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Busca los dos paraderos enfrentados en una esquina dada por dos calles.
    Retorna (stop_ida, stop_vuelta).
    """
    if not os.path.exists(DB_PATH) or not street1:
        return None, None

    s1 = street1.strip()
    s2 = street2.strip() if street2 else ""

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        query = "SELECT code, name, lat, lon FROM stops WHERE name LIKE ?"
        params = [f"%{s1}%"]
        if s2:
            query += " AND name LIKE ?"
            params.append(f"%{s2}%")

        c.execute(query, tuple(params))
        rows = c.fetchall()
        conn.close()

        if not rows:
            return None, None

        # Paradero principal de referencia
        p1_code, p1_name, p1_lat, p1_lon = rows[0]
        stop_ida = {
            "code": p1_code,
            "name": clean_intersection_name(p1_name),
            "latitude": p1_lat,
            "longitude": p1_lon,
            "distance_meters": 0
        }

        # Si encontramos dos directamente en la consulta
        if len(rows) >= 2:
            p2_code, p2_name, p2_lat, p2_lon = rows[1]
            stop_vuelta = {
                "code": p2_code,
                "name": clean_intersection_name(p2_name),
                "latitude": p2_lat,
                "longitude": p2_lon,
                "distance_meters": 0
            }
            return stop_ida, stop_vuelta

        # Si solo encontramos uno con ambos nombres, buscar su opuesto en la vereda del frente
        opposing = find_opposing_stop(p1_code)
        return stop_ida, opposing
    except Exception as e:
        logger.error(f"Error buscando paraderos por esquina {street1} con {street2}: {e}", exc_info=True)
        return None, None


def clean_spoken_stop_code(code: str) -> str:
    """
    Formatea un código de paradero para que Alexa pronuncie las letras deletreadas
    y el número entero. Ej: 'PD184' -> 'P D 184' ('P D ciento ochenta y cuatro').
    """
    if not code:
        return ""
    clean = code.strip().upper()
    match = re.match(r"^([A-Z]+)(\d+)$", clean)
    if match:
        letters = " ".join(list(match.group(1)))
        number = match.group(2)
        return f"{letters} {number}"
    return clean


def normalize_destination_query(query: str, default_city: str = "Santiago", country: str = "Chile") -> str:
    """
    Normaliza el texto de destino dicho por el usuario para maximizar el acierto en OpenStreetMap Nominatim.
    Convierte 'con', 'y', 'esq' en ' / ' y agrega ciudad y país si no están presentes.
    """
    if not query:
        return ""
    q = query.strip()
    # Reemplazar intersecciones
    q = re.sub(r"\s+(?:con|y|esq\.?|esquina)\s+", " / ", q, flags=re.IGNORECASE)
    # Limpieza de espacios
    q = re.sub(r"\s+", " ", q).strip()
    # Agregar ciudad y país si no están
    if default_city.lower() not in q.lower():
        q = f"{q}, {default_city}"
    if country.lower() not in q.lower():
        q = f"{q}, {country}"
    return q


