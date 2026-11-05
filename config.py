import os
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Cargar variables desde .env si existe
load_dotenv()

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

# -------------------------------------------------------------------------
# Configuración Multi-Usuario (Perfiles de Voz y Tarjetas Bip!)
# -------------------------------------------------------------------------
USERS_BIP: Dict[str, Dict[str, Any]] = {
    "user1": {
        "name": os.getenv("USER1_NAME", "Simón"),
        "aliases": ["simon", "simón", "yo", "mío", "mio", "mía", "mia", "mi"],
        "card": os.getenv("USER1_BIP", DEFAULT_BIP_NUMBER).strip(),
        "stop": os.getenv("USER1_STOP", DEFAULT_STOP_CODE).strip().upper(),
        "service": os.getenv("USER1_SERVICE", DEFAULT_SERVICE).strip().upper(),
        "person_id": os.getenv("USER1_PERSON_ID", "").strip()
    },
    "user2": {
        "name": os.getenv("USER2_NAME", "María"),
        "aliases": ["maria", "maría", "pareja", "polola", "esposa", "hermana", "mama", "mamá"],
        "card": os.getenv("USER2_BIP", "87654321").strip(),
        "stop": os.getenv("USER2_STOP", "PC186").strip().upper(),
        "service": os.getenv("USER2_SERVICE", "506").strip().upper(),
        "person_id": os.getenv("USER2_PERSON_ID", "").strip()
    }
}


def resolve_user(name_query: Optional[str] = None, person_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Identifica cuál usuario está consultando:
    1. Si Alexa reconoció la voz mediante Voice ID (person_id).
    2. Si el usuario dijo explícitamente el nombre (ej: 'la Bip de María').
    3. Si no se puede identificar, retorna el Usuario 1 por defecto.
    """
    # 1. Por Voice Profile ID
    if person_id:
        for u in USERS_BIP.values():
            if u["person_id"] and u["person_id"] == person_id:
                return u

    # 2. Por Nombre / Alias
    if name_query:
        clean = name_query.strip().lower()
        for u in USERS_BIP.values():
            if clean in u["aliases"] or clean == u["name"].lower():
                return u

    # 3. Fallback: Usuario 1
    return USERS_BIP["user1"]
