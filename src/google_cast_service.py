from collections import OrderedDict
import io
import logging
import re
import socket
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from gtts import gTTS
import pychromecast

import config

try:
    from src.location_service import clean_spoken_stop_code
except ImportError:
    try:
        from location_service import clean_spoken_stop_code
    except ImportError:
        def clean_spoken_stop_code(code: str) -> str:
            return code

logger = logging.getLogger(__name__)

MAX_TTS_CLIPS = 10
CAST_DISCOVERY_TIMEOUT = 5.0
CAST_PLAYBACK_MAX_WAIT = 20.0

_tts_clips: "OrderedDict[str, bytes]" = OrderedDict()
_clip_lock = threading.Lock()
_speak_lock = threading.Lock()


def normalize_speech_for_tts(text: str) -> str:
    """Convierte códigos de paradero (ej: PD289 -> P D 289) para pronunciación clara en TTS."""
    if not text:
        return ""
    return re.sub(
        r"\b(P[A-J]\d{1,4})\b",
        lambda m: clean_spoken_stop_code(m.group(1)),
        text,
        flags=re.IGNORECASE,
    )


def create_tts_clip(text: str) -> str:
    """Sintetiza texto en español a MP3 en RAM y retorna su clip_id."""
    spoken_text = normalize_speech_for_tts(text)
    buf = io.BytesIO()
    tts = gTTS(text=spoken_text, lang="es")
    tts.write_to_fp(buf)
    audio_bytes = buf.getvalue()

    clip_id = uuid.uuid4().hex
    with _clip_lock:
        _tts_clips[clip_id] = audio_bytes
        while len(_tts_clips) > MAX_TTS_CLIPS:
            _tts_clips.popitem(last=False)
    return clip_id


def get_tts_clip(clip_id: str) -> Optional[bytes]:
    """Obtiene los bytes MP3 de un clip desde RAM, o None si no existe o fue evictado."""
    with _clip_lock:
        return _tts_clips.get(clip_id)


def clear_tts_clips() -> None:
    """Limpia el buffer circular de clips TTS en memoria (útil en tests)."""
    with _clip_lock:
        _tts_clips.clear()


def get_local_ip() -> str:
    """Retorna LOCAL_SERVER_IP de .env si está definida o autodetecta la IP LAN."""
    configured = (getattr(config, "LOCAL_SERVER_IP", "") or "").strip()
    if configured:
        return configured

    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError as exc:
        logger.warning(f"No se pudo autodeterminar IP LAN local, usando 127.0.0.1: {exc}")
        return "127.0.0.1"
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def _extract_cast_info(cast: Any) -> Dict[str, Any]:
    info = getattr(cast, "cast_info", None)
    return {
        "name": getattr(info, "friendly_name", None) or getattr(cast, "name", "") or "",
        "model_name": getattr(info, "model_name", None) or getattr(cast, "model_name", "") or "",
        "cast_type": getattr(info, "cast_type", None) or getattr(cast, "cast_type", "") or "",
        "uuid": str(getattr(info, "uuid", "") or ""),
        "host": getattr(info, "host", "") or "",
        "port": getattr(info, "port", 8009) or 8009,
    }


def list_cast_devices(timeout: float = CAST_DISCOVERY_TIMEOUT) -> List[Dict[str, Any]]:
    """Lista los dispositivos Google Cast visibles en la red local."""
    browser = None
    try:
        casts, browser = pychromecast.get_chromecasts(timeout=timeout)
        return [_extract_cast_info(c) for c in casts]
    except Exception as exc:
        logger.error(f"Error descubriendo dispositivos Google Cast: {exc}", exc_info=True)
        return []
    finally:
        if browser is not None:
            try:
                pychromecast.discovery.stop_discovery(browser)
            except Exception:
                pass


def _match_target_cast(casts: List[Any], target_name: str) -> Optional[Any]:
    for cast in casts:
        if _extract_cast_info(cast)["name"] == target_name:
            return cast
    target_lower = target_name.lower()
    for cast in casts:
        if _extract_cast_info(cast)["name"].lower() == target_lower:
            return cast
    return None


def speak_on_home(text: str, device_name: Optional[str] = None) -> bool:
    """
    Convierte text a voz en español y lo reproduce exclusivamente en el parlante Cast
    configurado en GOOGLE_CAST_DEVICE (o device_name).
    """
    raw_name = device_name if device_name is not None else getattr(config, "GOOGLE_CAST_DEVICE", "")
    target_name = (raw_name or "").strip()
    if not target_name:
        logger.error("GOOGLE_CAST_DEVICE no configurado; se omite reproducción para evitar tocar la TV.")
        return False

    if not text or not text.strip():
        return False

    with _speak_lock:
        browser = None
        target_cast = None
        try:
            casts, browser = pychromecast.get_listed_chromecasts(
                friendly_names=[target_name],
                discovery_timeout=CAST_DISCOVERY_TIMEOUT,
            )
            target_cast = _match_target_cast(casts, target_name)
            if target_cast is None:
                logger.warning(
                    f"Parlante Google Cast '{target_name}' no encontrado en la red local."
                )
                return False

            target_cast.wait(timeout=CAST_DISCOVERY_TIMEOUT)
            clip_id = create_tts_clip(text)
            port = getattr(config, "PORT", 8000)
            media_url = f"http://{get_local_ip()}:{port}/api/tts/{clip_id}.mp3"

            mc = target_cast.media_controller
            mc.play_media(media_url, "audio/mpeg")
            mc.block_until_active(timeout=CAST_DISCOVERY_TIMEOUT)

            deadline = time.monotonic() + CAST_PLAYBACK_MAX_WAIT
            while (
                getattr(getattr(mc, "status", None), "player_state", None) in ("PLAYING", "BUFFERING")
                and time.monotonic() < deadline
            ):
                time.sleep(0.25)

            logger.info(f"Reproducción Google Cast completada en '{target_name}' (clip={clip_id})")
            return True
        except Exception as exc:
            logger.error(f"Error reproduciendo voz por Google Cast en '{target_name}': {exc}", exc_info=True)
            return False
        finally:
            if target_cast is not None:
                try:
                    target_cast.disconnect(timeout=2.0)
                except Exception:
                    pass
            if browser is not None:
                try:
                    pychromecast.discovery.stop_discovery(browser)
                except Exception:
                    pass
