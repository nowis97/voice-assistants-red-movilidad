import os
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
