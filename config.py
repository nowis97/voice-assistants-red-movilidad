import os
import json
import re
import logging
from typing import Optional, Dict, Any, List, Tuple
from dotenv import load_dotenv

# Cargar variables desde .env si existe
load_dotenv()

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(BASE_DIR, "users.json")

DEFAULT_BIP_NUMBER = os.getenv("DEFAULT_BIP_NUMBER", "12345678")
DEFAULT_STOP_CODE = os.getenv("DEFAULT_STOP_CODE", "PA345").strip().upper()
DEFAULT_SERVICE = os.getenv("DEFAULT_SERVICE", "401").strip().upper()
ALEXA_SKILL_ID = os.getenv("ALEXA_SKILL_ID", "")
PORT = int(os.getenv("PORT", "8000"))

# Headers oficiales extraídos de la ingeniería inversa de la app Red Movilidad
RED_HEADERS = {
    "Accept": "application/json",
    "Os-Type": "Android",
    "App-Version": "5.18.6",
    "Phone-Id": "9d756ff1-bd35-4edb-96df-ecbda9843022",
    "User-Agent": "okhttp/4.9.0",
}

SPANISH_WORDS = {
    "cero": "0", "uno": "1", "un": "1", "dos": "2", "tres": "3",
    "cuatro": "4", "cinco": "5", "seis": "6", "siete": "7", "ocho": "8", "nueve": "9",
    "diez": "10", "once": "11", "doce": "12", "trece": "13", "catorce": "14",
    "quince": "15", "dieciseis": "16", "diecisiete": "17", "dieciocho": "18", "diecinueve": "19",
    "veinte": "20", "veintiuno": "21", "veintidos": "22", "veintitres": "23",
    "treinta": "30", "cuarenta": "40", "cincuenta": "50", "sesenta": "60",
    "setenta": "70", "ochenta": "80", "noventa": "90", "cien": "100"
}

LETTER_WORDS = {
    "pe a": "PA", "pe ce": "PC", "pe i": "PI", "pe de": "PD", "pe be": "PB",
    "pe efe": "PF", "pe ge": "PG", "pe hache": "PH", "pe jota": "PJ", "pe e": "PE",
    "be": "B", "ce": "C", "de": "D", "efe": "F", "ge": "G", "hache": "H", "jota": "J",
    "i latina": "I"
}

DIGIT_WORDS = {
    "cero": "0", "uno": "1", "un": "1", "dos": "2", "tres": "3",
    "cuatro": "4", "cinco": "5", "seis": "6", "siete": "7", "ocho": "8", "nueve": "9"
}


def clean_alphanumeric_code(raw: Optional[str]) -> str:
    """Normaliza códigos alfanuméricos de paraderos y recorridos (ej: 'pe a tres cuatro cinco' -> 'PA345', 'be 02' -> 'B02', '506 e' -> '506E')."""
    if not raw:
        return ""
    t = str(raw).lower().strip()
    for phrase, rep in LETTER_WORDS.items():
        t = re.sub(r"\b" + phrase + r"\b", rep, t)
    for w, d in DIGIT_WORDS.items():
        t = re.sub(r"\b" + w + r"\b", d, t)
    t = re.sub(r"[\s\.\-]+", "", t)
    return t.upper()


def clean_card_number(raw: Optional[str]) -> str:
    """Extrae dígitos de una entrada de voz (admite números y palabras en español)."""
    if not raw:
        return ""
    raw_str = str(raw).strip()
    digits_only = re.sub(r"\D", "", raw_str)
    if len(digits_only) >= 6:
        return digits_only

    # Intento de parsear palabras en español dictadas
    words = re.findall(r"[a-zA-ZáéíóúÁÉÍÓÚñÑ]+", raw_str.lower())
    converted = []
    for w in words:
        if w in SPANISH_WORDS:
            converted.append(SPANISH_WORDS[w])
    res = "".join(converted)
    digits_res = re.sub(r"\D", "", res)
    return digits_res if len(digits_res) >= 6 else digits_only


def _get_default_users() -> Dict[str, Dict[str, Any]]:
    """Genera la estructura por defecto inicial desde variables de entorno."""
    return {
        "user1": {
            "name": os.getenv("USER1_NAME", "Simón"),
            "aliases": ["simon", "simón", "yo", "mío", "mio", "mía", "mia", "mi", "usuario 1"],
            "card": os.getenv("USER1_BIP", DEFAULT_BIP_NUMBER).strip(),
            "stop": os.getenv("USER1_STOP", DEFAULT_STOP_CODE).strip().upper(),
            "service": os.getenv("USER1_SERVICE", DEFAULT_SERVICE).strip().upper(),
            "person_id": os.getenv("USER1_PERSON_ID", "").strip()
        },
        "user2": {
            "name": os.getenv("USER2_NAME", "María"),
            "aliases": ["maria", "maría", "pareja", "polola", "esposa", "hermana", "mama", "mamá", "usuario 2"],
            "card": os.getenv("USER2_BIP", "87654321").strip(),
            "stop": os.getenv("USER2_STOP", "PC186").strip().upper(),
            "service": os.getenv("USER2_SERVICE", "506").strip().upper(),
            "person_id": os.getenv("USER2_PERSON_ID", "").strip()
        }
    }


def load_users() -> Dict[str, Dict[str, Any]]:
    """Carga los usuarios desde users.json o crea el archivo con los valores por defecto."""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and data:
                    return data
        except Exception as e:
            logger.warning(f"No se pudo leer {USERS_FILE}: {e}. Usando valores por defecto.")

    defaults = _get_default_users()
    save_users(defaults)
    return defaults


def save_users(users: Dict[str, Dict[str, Any]]) -> None:
    """Guarda los usuarios en users.json."""
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error guardando {USERS_FILE}: {e}")


# Diccionario global para compatibilidad
USERS_BIP = load_users()


def resolve_user(name_query: Optional[str] = None, person_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Identifica cuál usuario está consultando:
    1. Si Alexa reconoció la voz mediante Voice ID (person_id).
    2. Si el usuario dijo explícitamente el nombre (ej: 'la Bip de María').
    3. Si no se puede identificar, retorna el Usuario 1 por defecto.
    """
    users = load_users()

    # 1. Por Voice Profile ID
    if person_id:
        for u in users.values():
            if u.get("person_id") and u["person_id"] == person_id:
                return u

    # 2. Por Nombre / Alias
    if name_query:
        clean = name_query.strip().lower()
        for u in users.values():
            aliases = [a.lower() for a in u.get("aliases", [])]
            if clean in aliases or clean == u.get("name", "").lower():
                return u

    # 3. Fallback: Usuario 1
    return users.get("user1", next(iter(users.values())))


def save_card(
    card_number: str,
    name_query: Optional[str] = None,
    person_id: Optional[str] = None
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Guarda o actualiza el número de tarjeta Bip de un usuario.
    Retorna (éxito, mensaje, usuario_actualizado).
    """
    clean_card = clean_card_number(card_number)
    if not clean_card or len(clean_card) < 6 or len(clean_card) > 12:
        return False, "El número de tarjeta no es válido. Debe tener entre 7 y 9 dígitos.", {}

    users = load_users()
    target_key = None

    # Si hay person_id reconocido, asociarlo a ese usuario existente
    if person_id:
        for k, u in users.items():
            if u.get("person_id") == person_id:
                target_key = k
                break

    # Si se especificó nombre
    if not target_key and name_query:
        clean_name = name_query.strip().lower()
        for k, u in users.items():
            aliases = [a.lower() for a in u.get("aliases", [])]
            if clean_name in aliases or clean_name == u.get("name", "").lower():
                target_key = k
                break

        # Si no existe, revisar si es nombre nuevo
        if not target_key:
            if clean_name in ["yo", "mi", "mío", "mio", "mía", "mia"]:
                target_key = "user1"
            elif "user2" in users and users["user2"].get("name") in ["María", "maria", ""]:
                # Si user2 es el slot secundario estándar, podemos asignarlo
                target_key = "user2"
                users[target_key]["name"] = name_query.strip().capitalize()
                users[target_key]["aliases"].append(clean_name)
            else:
                # Crear nuevo perfil de usuario
                target_key = f"user_{len(users) + 1}"
                users[target_key] = {
                    "name": name_query.strip().capitalize(),
                    "aliases": [clean_name],
                    "card": clean_card,
                    "stop": DEFAULT_STOP_CODE,
                    "service": DEFAULT_SERVICE,
                    "person_id": person_id or ""
                }

    # Fallback por defecto a user1
    if not target_key:
        target_key = "user1"

    # Actualizar datos
    users[target_key]["card"] = clean_card
    if person_id:
        users[target_key]["person_id"] = person_id

    save_users(users)
    global USERS_BIP
    USERS_BIP = users

    user_name = users[target_key].get("name", "Usuario")
    return True, f"Tarjeta {clean_card} guardada para {user_name}.", users[target_key]


def save_preference(
    stop: Optional[str] = None,
    service: Optional[str] = None,
    name_query: Optional[str] = None,
    person_id: Optional[str] = None
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Guarda o actualiza el paradero y/o micro favorita de un usuario.
    """
    users = load_users()
    target_key = "user1"

    if person_id:
        for k, u in users.items():
            if u.get("person_id") == person_id:
                target_key = k
                break
    elif name_query:
        clean_name = name_query.strip().lower()
        for k, u in users.items():
            aliases = [a.lower() for a in u.get("aliases", [])]
            if clean_name in aliases or clean_name == u.get("name", "").lower():
                target_key = k
                break

    target_user = users.get(target_key, users["user1"])

    updates = []
    if stop:
        clean_stop = clean_alphanumeric_code(stop)
        target_user["stop"] = clean_stop
        updates.append(f"paradero {clean_stop}")

    if service:
        clean_service = clean_alphanumeric_code(service)
        target_user["service"] = clean_service
        updates.append(f"recorrido {clean_service}")

    save_users(users)
    global USERS_BIP
    USERS_BIP = users

    desc = " y ".join(updates) if updates else "preferencias"
    return True, f"Guardé {desc} para {target_user['name']}.", target_user


def list_configured_users() -> List[Dict[str, Any]]:
    """Retorna un listado de usuarios configurados con datos sensibles enmascarados."""
    users = load_users()
    res = []
    for k, u in users.items():
        card = u.get("card", "")
        masked = f"...{card[-4:]}" if len(card) >= 4 else card
        res.append({
            "key": k,
            "name": u.get("name", "Usuario"),
            "card_masked": masked,
            "card_full": card,
            "stop": u.get("stop", DEFAULT_STOP_CODE),
            "service": u.get("service", DEFAULT_SERVICE),
            "has_voice_id": bool(u.get("person_id"))
        })
    return res
