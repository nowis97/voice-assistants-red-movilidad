import base64
from collections import OrderedDict
import hashlib
import hmac
import html
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import config

try:
    from src import google_cast_service, red_service
    from src.bus_watcher import watcher_manager
except ImportError:
    import google_cast_service
    import red_service
    from bus_watcher import watcher_manager

logger = logging.getLogger(__name__)

router = APIRouter()

AGENT_USER_ID = "google-home-user1"
WATCHER_USER_ID = "google_home"
MOMENTARY_DEVICES = {"red_saldo_bip", "red_micro_habitual", "red_alcanzo_salir"}
ALL_DEVICES = MOMENTARY_DEVICES | {"red_vigilante"}
ALLOWED_REDIRECT_PREFIXES = (
    "https://oauth-redirect.googleusercontent.com/r/",
    "https://oauth-redirect-sandbox.googleusercontent.com/r/",
)
CODE_TTL_SECONDS = 300
ACCESS_TTL_SECONDS = 3600
MAX_USED_CODES = 256

_used_codes: "OrderedDict[str, int]" = OrderedDict()
_used_codes_lock = threading.Lock()


def _mark_code_used(code: str, exp: int) -> bool:
    """Atomically checks and records an authorization code.
    Returns True if the code was not used before and was successfully marked.
    Returns False if the code was already used.
    Prunes expired codes and bounds the cache size.
    """
    now = int(time.time())
    with _used_codes_lock:
        expired = [c for c, e in _used_codes.items() if e <= now]
        for c in expired:
            del _used_codes[c]

        if code in _used_codes:
            return False

        while len(_used_codes) >= MAX_USED_CODES:
            _used_codes.popitem(last=False)

        _used_codes[code] = exp
        return True


def clear_used_codes() -> None:
    """Limpia el caché de códigos usados (para pruebas)."""
    with _used_codes_lock:
        _used_codes.clear()


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign_token(payload: Dict[str, Any], secret: str) -> str:
    body = _b64u_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = _b64u_encode(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def _verify_token(token: str, secret: str, expected_kind: str) -> Optional[Dict[str, Any]]:
    try:
        if not token or not secret or "." not in token:
            return None
        parts = token.split(".", 1)
        if len(parts) != 2:
            return None
        body, sig = parts
        expected_sig = _b64u_encode(hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(_b64u_decode(body).decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("kind") != expected_kind:
            return None
        exp = payload.get("exp", 0)
        if exp and time.time() > exp:
            return None
        return payload
    except Exception:
        return None


def _is_oauth_configured() -> bool:
    return bool(
        (getattr(config, "GOOGLE_OAUTH_CLIENT_ID", "") or "").strip()
        and (getattr(config, "GOOGLE_OAUTH_CLIENT_SECRET", "") or "").strip()
        and (getattr(config, "GOOGLE_OAUTH_PIN", "") or "").strip()
    )


def _is_allowed_redirect_uri(redirect_uri: str) -> bool:
    return bool(redirect_uri and redirect_uri.startswith(ALLOWED_REDIRECT_PREFIXES))


def _append_query_params(url: str, params: Dict[str, str]) -> str:
    parsed = urlparse(url)
    existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
    existing.update({k: v for k, v in params.items() if v is not None})
    new_query = urlencode(existing)
    return urlunparse(parsed._replace(query=new_query))


def _render_login_html(
    client_id: str,
    redirect_uri: str,
    state: str,
    error_message: str = "",
) -> str:
    err_block = f'<p style="color:#c62828;font-weight:bold">{html.escape(error_message)}</p>' if error_message else ""
    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Red Movilidad - Autorizar Google Home</title></head>
<body style="font-family:sans-serif;max-width:400px;margin:40px auto;padding:16px">
<h2>Red Movilidad</h2>
<p>Ingresa tu PIN para vincular Google Home.</p>
{err_block}
<form method="post">
  <input type="hidden" name="client_id" value="{html.escape(client_id, quote=True)}">
  <input type="hidden" name="redirect_uri" value="{html.escape(redirect_uri, quote=True)}">
  <input type="hidden" name="state" value="{html.escape(state, quote=True)}">
  <label for="pin">PIN personal:</label><br>
  <input id="pin" name="pin" type="password" inputmode="numeric" required style="width:100%;padding:10px;margin:8px 0 16px"><br>
  <button type="submit" style="width:100%;padding:12px;font-size:16px">Autorizar Google Home</button>
</form>
</body></html>"""


async def _parse_form_data(request: Request) -> Dict[str, str]:
    try:
        body = await request.body()
        return dict(parse_qsl(body.decode("utf-8"), keep_blank_values=True))
    except Exception:
        return {}


@router.get("/google/oauth/auth")
def oauth_authorize_get(
    client_id: str = "",
    redirect_uri: str = "",
    state: str = "",
    response_type: str = "code",
):
    if not _is_oauth_configured():
        logger.error("Google OAuth2 sin configurar en .env (CLIENT_ID/SECRET/PIN vacíos)")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OAuth no configurado")

    expected_client = config.GOOGLE_OAUTH_CLIENT_ID
    if not hmac.compare_digest(client_id, expected_client) or response_type != "code" or not _is_allowed_redirect_uri(redirect_uri):
        logger.warning(f"OAuth GET inválido: client_id={client_id}, redirect_uri={redirect_uri}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Parámetros OAuth inválidos")

    return HTMLResponse(_render_login_html(client_id, redirect_uri, state))


@router.post("/google/oauth/auth")
async def oauth_authorize_post(request: Request):
    if not _is_oauth_configured():
        logger.error("Google OAuth2 sin configurar en .env (CLIENT_ID/SECRET/PIN vacíos)")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OAuth no configurado")

    form = await _parse_form_data(request)
    client_id = str(form.get("client_id", ""))
    redirect_uri = str(form.get("redirect_uri", ""))
    state = str(form.get("state", ""))
    pin = str(form.get("pin", ""))

    if not hmac.compare_digest(client_id, config.GOOGLE_OAUTH_CLIENT_ID) or not _is_allowed_redirect_uri(redirect_uri):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Parámetros OAuth inválidos")

    if not hmac.compare_digest(pin, config.GOOGLE_OAUTH_PIN):
        logger.warning("Intento de autorización Google Home con PIN incorrecto")
        return HTMLResponse(
            _render_login_html(client_id, redirect_uri, state, "PIN incorrecto. Intenta nuevamente."),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    code = _sign_token(
        {
            "kind": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "exp": int(time.time()) + CODE_TTL_SECONDS,
        },
        config.GOOGLE_OAUTH_CLIENT_SECRET,
    )
    params = {"code": code}
    if state:
        params["state"] = state
    target_url = _append_query_params(redirect_uri, params)
    logger.info("Código de autorización Google Home emitido correctamente")
    return RedirectResponse(url=target_url, status_code=status.HTTP_302_FOUND)


def _extract_client_credentials(request: Request, form: Any) -> Tuple[str, str]:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
            if ":" in decoded:
                cid, csec = decoded.split(":", 1)
                return cid, csec
        except Exception:
            return "", ""
    return str(form.get("client_id", "")), str(form.get("client_secret", ""))


@router.post("/google/oauth/token")
async def oauth_token(request: Request):
    if not _is_oauth_configured():
        return JSONResponse({"error": "server_error"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    form = await _parse_form_data(request)
    client_id, client_secret = _extract_client_credentials(request, form)
    if not (
        hmac.compare_digest(client_id, config.GOOGLE_OAUTH_CLIENT_ID)
        and hmac.compare_digest(client_secret, config.GOOGLE_OAUTH_CLIENT_SECRET)
    ):
        logger.warning("Rechazada solicitud OAuth token por credenciales de cliente inválidas")
        return JSONResponse({"error": "invalid_client"}, status_code=status.HTTP_400_BAD_REQUEST)

    grant_type = str(form.get("grant_type", ""))
    secret = config.GOOGLE_OAUTH_CLIENT_SECRET

    if grant_type == "authorization_code":
        code = str(form.get("code", ""))
        redirect_uri = str(form.get("redirect_uri", ""))
        payload = _verify_token(code, secret, expected_kind="code")
        if (
            not payload
            or payload.get("client_id") != client_id
            or payload.get("redirect_uri") != redirect_uri
        ):
            return JSONResponse({"error": "invalid_grant"}, status_code=status.HTTP_400_BAD_REQUEST)

        code_exp = int(payload.get("exp", 0))
        if not _mark_code_used(code, code_exp):
            logger.warning("Intento de reutilizar código de autorización OAuth ya canjeado")
            return JSONResponse({"error": "invalid_grant"}, status_code=status.HTTP_400_BAD_REQUEST)

        now = int(time.time())
        access_token = _sign_token(
            {"kind": "access", "sub": AGENT_USER_ID, "exp": now + ACCESS_TTL_SECONDS},
            secret,
        )
        refresh_token = _sign_token(
            {"kind": "refresh", "sub": AGENT_USER_ID, "client_id": client_id, "exp": 0},
            secret,
        )
        logger.info("Tokens OAuth2 emitidos para vinculación Google Home")
        return {
            "token_type": "Bearer",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": ACCESS_TTL_SECONDS,
        }

    if grant_type == "refresh_token":
        refresh_token = str(form.get("refresh_token", ""))
        payload = _verify_token(refresh_token, secret, expected_kind="refresh")
        if not payload or payload.get("client_id") != client_id:
            return JSONResponse({"error": "invalid_grant"}, status_code=status.HTTP_400_BAD_REQUEST)

        access_token = _sign_token(
            {"kind": "access", "sub": AGENT_USER_ID, "exp": int(time.time()) + ACCESS_TTL_SECONDS},
            secret,
        )
        logger.info("Access token renovado vía refresh_token para Google Home")
        return {
            "token_type": "Bearer",
            "access_token": access_token,
            "expires_in": ACCESS_TTL_SECONDS,
        }

    return JSONResponse({"error": "unsupported_grant_type"}, status_code=status.HTTP_400_BAD_REQUEST)


def _device_definition(device_id: str, name: str) -> Dict[str, Any]:
    return {
        "id": device_id,
        "type": "action.devices.types.SWITCH",
        "traits": ["action.devices.traits.OnOff"],
        "name": {"defaultNames": [name], "name": name, "nicknames": [name]},
        "willReportState": False,
        "attributes": {"commandOnlyOnOff": False, "queryOnlyOnOff": False},
        "deviceInfo": {
            "manufacturer": "Red Movilidad Local",
            "model": "VirtualSwitch-v1",
            "hwVersion": "1.0",
            "swVersion": "1.0",
        },
    }


def _build_sync_devices() -> List[Dict[str, Any]]:
    return [
        _device_definition("red_saldo_bip", "Saldo Bip"),
        _device_definition("red_micro_habitual", "Micro habitual"),
        _device_definition("red_alcanzo_salir", "Alcanzo a salir"),
        _device_definition("red_vigilante", "Modo vigilante"),
    ]


def execute_device_action(device_id: str, turn_on: bool) -> None:
    """Ejecuta la consulta o cambio de Modo Vigilante y habla la respuesta por Google Cast."""
    try:
        if device_id in MOMENTARY_DEVICES and not turn_on:
            return

        user_info = config.resolve_user()
        user_stops = config.get_user_stops(user_key_or_name=user_info.get("name"))

        if device_id == "red_saldo_bip":
            speech = red_service.format_balance_speech(
                bip_code=user_info.get("card"),
                user_name=user_info.get("name"),
            )
            google_cast_service.speak_on_home(speech)
            return

        if device_id == "red_micro_habitual":
            speech = red_service.format_dual_prediction_speech(
                linea=user_info.get("service") or config.DEFAULT_SERVICE,
                stop_ida=user_stops["ida"],
                stop_vuelta=user_stops.get("vuelta"),
                intersection=user_stops.get("intersection"),
            )
            google_cast_service.speak_on_home(speech)
            return

        if device_id == "red_alcanzo_salir":
            stop_code = user_stops["ida"]["code"]
            speech = red_service.format_travel_summary_speech(
                user_name=user_info.get("name"),
                card_number=user_info.get("card"),
                stop_code=stop_code,
                service=user_info.get("service"),
            )
            google_cast_service.speak_on_home(speech)
            return

        if device_id == "red_vigilante":
            if not turn_on:
                cancelled = watcher_manager.cancel_watch(WATCHER_USER_ID)
                msg = (
                    "Listo, cancelé la vigilancia de tu micro."
                    if cancelled
                    else "No hay ninguna vigilancia de micro activa en este momento."
                )
                google_cast_service.speak_on_home(msg)
                return

            clean_linea = config.clean_alphanumeric_code(user_info.get("service") or config.DEFAULT_SERVICE)
            stop_ida = user_stops["ida"]
            stop_code = stop_ida["code"]
            corner_name = user_stops.get("intersection") or stop_ida.get("name") or stop_code
            threshold = max(1, int(getattr(config, "GOOGLE_WATCH_THRESHOLD_MINUTES", 5)))

            try:
                pred = red_service.get_stop_predictions(stop_code, clean_linea)
                if pred.get("success") and pred.get("buses"):
                    min_time = pred["buses"][0].get("min_time", 0)
                    if min_time <= threshold:
                        google_cast_service.speak_on_home(
                            f"Tu micro {clean_linea} ya está muy cerca, a {min_time} minutos de tu esquina "
                            f"en {corner_name}. Es momento de salir ahora mismo."
                        )
                        return
            except Exception as exc:
                logger.warning(f"Error chequeo preliminar Google Vigilante: {exc}")

            watcher_manager.start_watch(
                user_id=WATCHER_USER_ID,
                linea=clean_linea,
                stop_code=stop_code,
                corner_name=corner_name,
                threshold_minutes=threshold,
                api_endpoint="",
                api_access_token="",
                notify_channel="google_cast",
            )
            google_cast_service.speak_on_home(
                f"Perfecto, estaré vigilando la micro {clean_linea} en tu esquina de {corner_name}. "
                f"Te avisaré apenas esté a {threshold} minutos."
            )
    except Exception as exc:
        logger.error(f"Error ejecutando acción Google Smart Home ({device_id}, on={turn_on}): {exc}", exc_info=True)


def _require_bearer_token(request: Request) -> None:
    auth_header = request.headers.get("authorization", "").strip()
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = auth_header[7:].strip()
    secret = (getattr(config, "GOOGLE_OAUTH_CLIENT_SECRET", "") or "").strip()
    if not _verify_token(token, secret, expected_kind="access"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")


@router.post("/google/smarthome")
async def smarthome_fulfillment(request: Request):
    _require_bearer_token(request)

    body = await request.json()
    request_id = body.get("requestId", "")
    inputs = body.get("inputs") or []
    if not inputs:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing inputs")

    first_input = inputs[0]
    intent = first_input.get("intent", "")
    logger.info(f"Google Smart Home intent recibido: {intent} (requestId={request_id})")

    if intent == "action.devices.SYNC":
        return {
            "requestId": request_id,
            "payload": {"agentUserId": AGENT_USER_ID, "devices": _build_sync_devices()},
        }

    if intent == "action.devices.QUERY":
        req_devices = (first_input.get("payload") or {}).get("devices", [])
        devices_state: Dict[str, Dict[str, Any]] = {}
        for dev in req_devices:
            dev_id = dev.get("id", "")
            if dev_id == "red_vigilante":
                devices_state[dev_id] = {
                    "on": watcher_manager.has_active_job(WATCHER_USER_ID),
                    "online": True,
                    "status": "SUCCESS",
                }
            elif dev_id in MOMENTARY_DEVICES:
                devices_state[dev_id] = {"on": False, "online": True, "status": "SUCCESS"}
            else:
                devices_state[dev_id] = {"online": False, "status": "ERROR", "errorCode": "deviceNotFound"}
        return {"requestId": request_id, "payload": {"devices": devices_state}}

    if intent == "action.devices.EXECUTE":
        results: List[Dict[str, Any]] = []
        for cmd in (first_input.get("payload") or {}).get("commands", []):
            cmd_devices = cmd.get("devices", [])
            executions = cmd.get("execution", [])
            for exc_item in executions:
                if exc_item.get("command") != "action.devices.commands.OnOff":
                    for dev in cmd_devices:
                        results.append(
                            {"ids": [dev.get("id", "")], "status": "ERROR", "errorCode": "functionNotSupported"}
                        )
                    continue

                turn_on = bool(exc_item.get("params", {}).get("on", False))
                for dev in cmd_devices:
                    dev_id = dev.get("id", "")
                    if dev_id not in ALL_DEVICES:
                        results.append({"ids": [dev_id], "status": "ERROR", "errorCode": "deviceNotFound"})
                        continue

                    threading.Thread(
                        target=execute_device_action,
                        args=(dev_id, turn_on),
                        daemon=True,
                    ).start()
                    reported_on = turn_on if dev_id == "red_vigilante" else False
                    results.append(
                        {
                            "ids": [dev_id],
                            "status": "SUCCESS",
                            "states": {"on": reported_on, "online": True},
                        }
                    )
        return {"requestId": request_id, "payload": {"commands": results}}

    if intent == "action.devices.DISCONNECT":
        logger.info("Cuenta Google Home desvinculada (DISCONNECT)")
        return {}

    return {"requestId": request_id, "payload": {}}
