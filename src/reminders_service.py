import logging
import requests
from datetime import datetime, timezone
from typing import Dict, Any

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 6


def has_reminder_permission(handler_input: Any) -> bool:
    """
    Verifica si el usuario otorgó permiso a la skill para crear recordatorios de Alexa.
    Revisa la presencia de consent_token en context.system.user.permissions.
    """
    try:
        context = handler_input.request_envelope.context
        system = context.system
        user = getattr(system, "user", None)
        if not user:
            return False
        permissions = getattr(user, "permissions", None)
        if not permissions:
            return False
        consent_token = getattr(permissions, "consent_token", None)
        return bool(consent_token)
    except Exception as e:
        logger.warning(f"Error comprobando permisos de recordatorios: {e}")
        return False


def create_spoken_reminder(
    api_endpoint: str,
    api_access_token: str,
    text: str,
    locale: str = "es-US"
) -> Dict[str, Any]:
    """
    Crea un recordatorio instantáneo que suena y habla en el parlante Alexa del usuario.
    Utiliza el endpoint oficial de Alexa Reminders API con disparo relativo inmediato (offset 0s).
    """
    clean_endpoint = (api_endpoint or "https://api.amazonalexa.com").rstrip("/")
    url = f"{clean_endpoint}/v1/alerts/reminders"
    headers = {
        "Authorization": f"Bearer {api_access_token}",
        "Content-Type": "application/json"
    }

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = {
        "requestTime": now_iso,
        "trigger": {
            "type": "SCHEDULED_RELATIVE",
            "offsetInSeconds": 0
        },
        "alertInfo": {
            "spokenInfo": {
                "content": [
                    {
                        "locale": locale,
                        "text": text
                    }
                ]
            }
        },
        "pushNotification": {
            "status": "ENABLED"
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT_SECONDS)
        if response.status_code in (200, 201):
            data = response.json()
            logger.info("Recordatorio de Alexa creado exitosamente")
            return {
                "success": True,
                "alert_token": data.get("alertToken", "")
            }
        else:
            logger.warning(f"Error creando recordatorio Alexa: HTTP {response.status_code} - {response.text}")
            return {
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text}"
            }
    except requests.RequestException as e:
        logger.error(f"Fallo de conexión con Alexa Reminders API: {e}")
        return {
            "success": False,
            "error": str(e)
        }
