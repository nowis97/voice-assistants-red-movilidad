# Google Home Smart Home & Cast TTS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable native Google Home speaker voice control for Red Movilidad (Saldo Bip, habitual bus arrival, "¿Alcanzo a salir?", and Modo Vigilante ON/OFF) via virtual Smart Home `SWITCH` devices in FastAPI and local Google Cast Spanish TTS playback targeting only the configured speaker.

**Architecture:** Extend the existing FastAPI server (`src/local_server.py`) with a Google Smart Home Cloud-to-Cloud router and stateless HMAC-SHA256 OAuth2 endpoints (`/google/oauth/auth`, `/google/oauth/token`, `/google/smarthome`) reachable through the existing Tailscale `/alexa` funnel (`https://nowis.tail7d0b63.ts.net/alexa/google/...`). `EXECUTE` commands respond HTTP 200 immediately and run Red Movilidad lookups + `gTTS` synthesis (stored in a 10-clip RAM `OrderedDict` served at `/api/tts/{clip_id}.mp3`) in a background thread, streaming playback exclusively via `pychromecast` to the exact friendly name configured in `GOOGLE_CAST_DEVICE` while leaving Android TV untouched.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, Requests, `gTTS>=2.5.0`, `pychromecast>=14.0.0`, Pytest, systemd, Tailscale Funnel.

**Spec:** `docs/superpowers/specs/2026-11-12-google-home-design.md`

## Global Constraints
- Preserve backward compatibility for all existing Alexa intents and API endpoints (`/alexa`, `/api/watcher/*`, `/api/saldo`, `/api/micro`, `/api/gps/*`).
- Never leave Zeroconf discovery threads or Chromecast sockets dangling on the Raspberry Pi 3; always call `pychromecast.discovery.stop_discovery(browser)` and `cast.disconnect(...)` in `finally` blocks.
- Strict speaker isolation: `speak_on_home` MUST match `GOOGLE_CAST_DEVICE` cleanly and return `False` if `GOOGLE_CAST_DEVICE` is empty or unmatched — never fall back to selecting an arbitrary Cast device (such as Android TV).
- Zero microSD wear from TTS audio: keep all generated MP3 clips strictly in an in-memory `OrderedDict` capped at 10 entries.
- Stop codes passed to `gTTS` must be phonetically spaced (`P[A-J]\d{1,4}` -> `P D 289`) without modifying bus route names (like `401c`).
- Fail closed on unconfigured or invalid OAuth credentials/PIN (`GOOGLE_OAUTH_PIN`, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`); support both `client_secret_post` and `client_secret_basic` at `/google/oauth/token`.
- Never alter Tailscale root routing `/` on port `3000` (reserved for Scrypted), and never commit `.env` or `users.json`.
- Every task follows strict TDD: failing test -> verify failure -> minimal implementation -> verify pass -> git commit.

---

### File Structure Map
- Modify: `config.py`, `.env.example`, `requirements.txt` — Google OAuth / Cast configuration env vars and dependencies (`pychromecast`, `gTTS`).
- Create: `src/google_cast_service.py` — Spanish TTS generation (`gTTS`), phonetic stop normalization, 10-clip RAM `OrderedDict`, LAN IP detection, strict Cast device discovery/playback.
- Create: `tests/test_google_cast_service.py` — Unit tests for clip eviction, phonetic normalization, strict device isolation, and Zeroconf cleanup.
- Modify: `src/bus_watcher.py` — Optional `notify_channel: str = "alexa"` field/parameter routing triggered alerts either to Alexa Reminders API or `google_cast_service.speak_on_home`.
- Modify: `tests/test_bus_watcher.py` — Unit test verifying `notify_channel="google_cast"` behavior without affecting Alexa alerts.
- Create: `src/google_smarthome.py` — Stateless HMAC-SHA256 OAuth2 endpoints (`/google/oauth/auth`, `/google/oauth/token`) and Smart Home webhook (`/google/smarthome` with `SYNC`, `QUERY`, `EXECUTE`, `DISCONNECT`) plus `execute_device_action`.
- Create: `tests/test_google_smarthome.py` — Full OAuth2 + Smart Home protocol + device execution tests.
- Modify: `src/local_server.py` — Mount `google_smarthome.router` and expose `GET /api/tts/{clip_id}.mp3` and `GET /api/cast/devices`.
- Modify: `tests/test_server_endpoints.py` — Verify `/api/tts/{clip_id}.mp3`, `/api/cast/devices`, and mounted `/google/oauth/auth`.

---

### Task 1: Dependencies, Config Env Vars & Google Cast TTS Service

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.example`
- Modify: `config.py`
- Create: `src/google_cast_service.py`
- Create: `tests/test_google_cast_service.py`

**Interfaces:**
- Consumes:
  - `config.GOOGLE_CAST_DEVICE: str`
  - `config.LOCAL_SERVER_IP: str`
  - `config.PORT: int`
  - `location_service.clean_spoken_stop_code(code: str) -> str`
- Produces:
  - `config.GOOGLE_OAUTH_CLIENT_ID: str`
  - `config.GOOGLE_OAUTH_CLIENT_SECRET: str`
  - `config.GOOGLE_OAUTH_PIN: str`
  - `config.GOOGLE_CAST_DEVICE: str`
  - `config.LOCAL_SERVER_IP: str`
  - `config.GOOGLE_WATCH_THRESHOLD_MINUTES: int`
  - `normalize_speech_for_tts(text: str) -> str`
  - `create_tts_clip(text: str) -> str`
  - `get_tts_clip(clip_id: str) -> Optional[bytes]`
  - `get_local_ip() -> str`
  - `list_cast_devices(timeout: float = 5.0) -> List[Dict[str, Any]]`
  - `speak_on_home(text: str, device_name: Optional[str] = None) -> bool`

- [ ] **Step 1: Install new dependencies in local Python environment and update `requirements.txt` and `.env.example`**

Run:
```powershell
python -m pip install "pychromecast>=14.0.0" "gTTS>=2.5.0"
```

Update `requirements.txt` by appending:
```text
pychromecast>=14.0.0
gTTS>=2.5.0
```

Update `.env.example` by appending:
```env

# Google Home Smart Home + Google Cast TTS
GOOGLE_OAUTH_CLIENT_ID=red-movilidad-google
GOOGLE_OAUTH_CLIENT_SECRET=
GOOGLE_OAUTH_PIN=
GOOGLE_CAST_DEVICE=
LOCAL_SERVER_IP=
GOOGLE_WATCH_THRESHOLD_MINUTES=5
```

- [ ] **Step 2: Write failing tests in `tests/test_google_cast_service.py`**

```python
import io
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
from src import google_cast_service


@pytest.fixture(autouse=True)
def clear_tts_buffer():
    google_cast_service.clear_tts_clips()
    yield
    google_cast_service.clear_tts_clips()


def test_config_exposes_google_home_settings():
    assert hasattr(config, "GOOGLE_OAUTH_CLIENT_ID")
    assert hasattr(config, "GOOGLE_OAUTH_CLIENT_SECRET")
    assert hasattr(config, "GOOGLE_OAUTH_PIN")
    assert hasattr(config, "GOOGLE_CAST_DEVICE")
    assert hasattr(config, "LOCAL_SERVER_IP")
    assert isinstance(config.GOOGLE_WATCH_THRESHOLD_MINUTES, int)
    assert config.GOOGLE_WATCH_THRESHOLD_MINUTES >= 1


def test_normalize_speech_for_tts_spaces_stop_codes_only():
    text = "La 401c llega al paradero PD289 y pa345 antes que la D03."
    normalized = google_cast_service.normalize_speech_for_tts(text)
    assert "P D 289" in normalized
    assert "P A 345" in normalized
    assert "401c" in normalized
    assert "D03" in normalized


def test_tts_ring_buffer_evicts_oldest_after_max_clips():
    def fake_gtts(text, lang="es"):
        inst = MagicMock()
        inst.write_to_fp.side_effect = lambda fp: fp.write(f"MP3:{text}".encode("utf-8"))
        return inst

    with patch("src.google_cast_service.gTTS", side_effect=fake_gtts):
        clip_ids = [google_cast_service.create_tts_clip(f"Mensaje {i}") for i in range(12)]

    # First 2 evicted, last 10 remain
    assert google_cast_service.get_tts_clip(clip_ids[0]) is None
    assert google_cast_service.get_tts_clip(clip_ids[1]) is None
    assert google_cast_service.get_tts_clip(clip_ids[2]) == b"MP3:Mensaje 2"
    assert google_cast_service.get_tts_clip(clip_ids[11]) == b"MP3:Mensaje 11"


def test_get_local_ip_prefers_config_override(monkeypatch):
    monkeypatch.setattr(config, "LOCAL_SERVER_IP", "192.168.0.115")
    assert google_cast_service.get_local_ip() == "192.168.0.115"


def test_list_cast_devices_extracts_info_and_stops_discovery():
    fake_cast_speaker = SimpleNamespace(
        cast_info=SimpleNamespace(
            friendly_name="Parlante Pieza",
            model_name="Google Home Mini",
            cast_type="audio",
            uuid="1111-2222",
            host="192.168.0.50",
            port=8009,
        )
    )
    fake_cast_tv = SimpleNamespace(
        cast_info=SimpleNamespace(
            friendly_name="Android TV",
            model_name="BRAVIA",
            cast_type="cast",
            uuid="3333-4444",
            host="192.168.0.60",
            port=8009,
        )
    )
    fake_browser = MagicMock()

    with patch(
        "src.google_cast_service.pychromecast.get_chromecasts",
        return_value=([fake_cast_speaker, fake_cast_tv], fake_browser),
    ), patch("src.google_cast_service.pychromecast.discovery.stop_discovery") as mock_stop:
        devices = google_cast_service.list_cast_devices(timeout=1.0)

    assert len(devices) == 2
    assert devices[0]["name"] == "Parlante Pieza"
    assert devices[0]["cast_type"] == "audio"
    assert devices[1]["name"] == "Android TV"
    mock_stop.assert_called_once_with(fake_browser)


def test_speak_on_home_fails_safely_when_device_name_empty(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CAST_DEVICE", "")
    with patch("src.google_cast_service.pychromecast.get_listed_chromecasts") as mock_discover:
        ok = google_cast_service.speak_on_home("Hola")
    assert ok is False
    mock_discover.assert_not_called()


def test_speak_on_home_ignores_non_matching_android_tv(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CAST_DEVICE", "Parlante Living")
    fake_tv = MagicMock()
    fake_tv.cast_info = SimpleNamespace(friendly_name="Android TV")
    fake_browser = MagicMock()

    with patch(
        "src.google_cast_service.pychromecast.get_listed_chromecasts",
        return_value=([fake_tv], fake_browser),
    ), patch("src.google_cast_service.pychromecast.discovery.stop_discovery") as mock_stop:
        ok = google_cast_service.speak_on_home("Hola")

    assert ok is False
    fake_tv.media_controller.play_media.assert_not_called()
    mock_stop.assert_called_once_with(fake_browser)


def test_speak_on_home_plays_on_exact_speaker_and_cleans_up(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CAST_DEVICE", "Parlante Living")
    monkeypatch.setattr(config, "LOCAL_SERVER_IP", "192.168.0.115")
    monkeypatch.setattr(config, "PORT", 8000)

    fake_speaker = MagicMock()
    fake_speaker.cast_info = SimpleNamespace(friendly_name="Parlante Living")
    fake_speaker.media_controller.status = SimpleNamespace(player_state="IDLE")
    fake_browser = MagicMock()

    def fake_gtts(text, lang="es"):
        inst = MagicMock()
        inst.write_to_fp.side_effect = lambda fp: fp.write(b"FAKE_MP3")
        return inst

    with patch("src.google_cast_service.gTTS", side_effect=fake_gtts), patch(
        "src.google_cast_service.pychromecast.get_listed_chromecasts",
        return_value=([fake_speaker], fake_browser),
    ), patch("src.google_cast_service.pychromecast.discovery.stop_discovery") as mock_stop:
        ok = google_cast_service.speak_on_home("Tu micro viene en PD289")

    assert ok is True
    fake_speaker.wait.assert_called_once_with(timeout=5.0)
    play_args, _ = fake_speaker.media_controller.play_media.call_args
    assert play_args[0].startswith("http://192.168.0.115:8000/api/tts/")
    assert play_args[0].endswith(".mp3")
    assert play_args[1] == "audio/mpeg"
    fake_speaker.media_controller.block_until_active.assert_called_once_with(timeout=5.0)
    fake_speaker.disconnect.assert_called_once_with(timeout=2.0)
    mock_stop.assert_called_once_with(fake_browser)


def test_speak_on_home_stops_discovery_on_cast_exception(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CAST_DEVICE", "Parlante Living")
    fake_speaker = MagicMock()
    fake_speaker.cast_info = SimpleNamespace(friendly_name="Parlante Living")
    fake_speaker.wait.side_effect = RuntimeError("Socket timeout")
    fake_browser = MagicMock()

    with patch(
        "src.google_cast_service.pychromecast.get_listed_chromecasts",
        return_value=([fake_speaker], fake_browser),
    ), patch("src.google_cast_service.pychromecast.discovery.stop_discovery") as mock_stop:
        ok = google_cast_service.speak_on_home("Hola")

    assert ok is False
    fake_speaker.disconnect.assert_called_once_with(timeout=2.0)
    mock_stop.assert_called_once_with(fake_browser)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_google_cast_service.py -v`
Expected: FAIL with `ImportError` / `ModuleNotFoundError: No module named 'src.google_cast_service'` and missing attributes on `config`.

- [ ] **Step 4: Add Google Home env settings to `config.py` and write `src/google_cast_service.py`**

Read lines 1-53 of `config.py` before editing to see exact placement right alongside `ALEXA_SKILL_ID` and `PORT`, then add:

```python
# Google Home Smart Home + Google Cast TTS
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "red-movilidad-google")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_OAUTH_PIN = os.getenv("GOOGLE_OAUTH_PIN", "")
GOOGLE_CAST_DEVICE = os.getenv("GOOGLE_CAST_DEVICE", "")
LOCAL_SERVER_IP = os.getenv("LOCAL_SERVER_IP", "")
try:
    GOOGLE_WATCH_THRESHOLD_MINUTES = max(1, int(os.getenv("GOOGLE_WATCH_THRESHOLD_MINUTES") or 5))
except ValueError:
    GOOGLE_WATCH_THRESHOLD_MINUTES = 5
```

Create `src/google_cast_service.py`:

```python
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
```

- [ ] **Step 5: Run unit tests to verify they pass**

Run: `python -m pytest tests/test_google_cast_service.py -v`
Expected: `9 passed`

- [ ] **Step 6: Commit**

```bash
git add requirements.txt .env.example config.py src/google_cast_service.py tests/test_google_cast_service.py
git commit -m "feat: add Google Cast TTS service and config settings"
```

---

### Task 2: Multi-Channel Notification Support (`notify_channel`) in `src/bus_watcher.py`

**Files:**
- Modify: `src/bus_watcher.py`
- Modify: `tests/test_bus_watcher.py`

**Interfaces:**
- Consumes:
  - `google_cast_service.speak_on_home(text: str, device_name: Optional[str] = None) -> bool`
- Produces:
  - `WatcherJob(..., notify_channel: str = "alexa")`
  - `BusWatcherManager.start_watch(..., notify_channel: str = "alexa") -> WatcherJob`

- [ ] **Step 1: Write failing test in `tests/test_bus_watcher.py`**

Append to `tests/test_bus_watcher.py`:

```python
def test_bus_watcher_triggers_google_cast_when_notify_channel_is_google_cast():
    manager = BusWatcherManager(poll_interval_seconds=0.05)

    mock_pred = {
        "success": True,
        "buses": [
            {"service": "513", "min_time": 3, "max_time": 4, "meters": 600}
        ]
    }

    with patch("src.red_service.get_stop_predictions", return_value=mock_pred), \
         patch("src.google_cast_service.speak_on_home", return_value=True) as mock_cast, \
         patch("src.reminders_service.create_spoken_reminder") as mock_remind:

        manager.start_watch(
            user_id="google_home",
            linea="513",
            stop_code="PD289",
            corner_name="José Arrieta con Ictinos",
            threshold_minutes=5,
            api_endpoint="",
            api_access_token="",
            notify_channel="google_cast",
        )

        time.sleep(0.2)
        assert mock_cast.called
        spoken_msg = mock_cast.call_args[0][0]
        assert "513" in spoken_msg
        assert "3" in spoken_msg
        assert not mock_remind.called
        assert manager.has_active_job("google_home") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_bus_watcher.py::test_bus_watcher_triggers_google_cast_when_notify_channel_is_google_cast -v`
Expected: FAIL with `TypeError: BusWatcherManager.start_watch() got an unexpected keyword argument 'notify_channel'`

- [ ] **Step 3: Implement `notify_channel` in `src/bus_watcher.py`**

Read `src/bus_watcher.py` to locate imports, `WatcherJob`, `start_watch`, and `_worker_loop`, then update:

1. Import `google_cast_service` using the existing fallback pattern:
```python
try:
    from src import google_cast_service
except ImportError:
    import google_cast_service
```

2. Add `notify_channel: str = "alexa"` to `WatcherJob`:
```python
@dataclass
class WatcherJob:
    job_id: str
    user_id: str
    linea: str
    stop_code: str
    corner_name: str
    threshold_minutes: int
    api_endpoint: str
    api_access_token: str
    created_at: float
    last_eta_minutes: Optional[int] = None
    checks_count: int = 0
    status: str = "active"
    notify_channel: str = "alexa"
```

3. Accept `notify_channel: str = "alexa"` in `BusWatcherManager.start_watch(...)` and pass it when instantiating `WatcherJob(..., notify_channel=notify_channel)`. Also include `"notify_channel": j.notify_channel` in `get_active_jobs()` entries.

4. In `_worker_loop`, where `min_time <= job.threshold_minutes`, dispatch on `job.notify_channel`:
```python
if job.notify_channel == "google_cast":
    cast_ok = google_cast_service.speak_on_home(spoken_text)
    if cast_ok:
        logger.info(
            f"[Watcher {job.job_id}] Aviso Google Cast entregado | "
            f"linea={job.linea}, eta={min_time}m"
        )
    else:
        logger.warning(
            f"[Watcher {job.job_id}] No se pudo entregar aviso Google Cast | "
            f"linea={job.linea}, eta={min_time}m"
        )
else:
    result = reminders_service.create_spoken_reminder(
        api_endpoint=job.api_endpoint,
        api_access_token=job.api_access_token,
        text=spoken_text
    )
    if result.get("success"):
        logger.info(
            f"[Watcher {job.job_id}] Recordatorio Alexa enviado | "
            f"linea={job.linea}, eta={min_time}m, alert_token={result.get('alert_token')}"
        )
    else:
        logger.warning(
            f"[Watcher {job.job_id}] Falló envío de recordatorio | "
            f"linea={job.linea}, error={result.get('error')}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bus_watcher.py -v`
Expected: `All tests in tests/test_bus_watcher.py pass`

- [ ] **Step 5: Commit**

```bash
git add src/bus_watcher.py tests/test_bus_watcher.py
git commit -m "feat: add google_cast notification channel to BusWatcherManager"
```

---

### Task 3: Google Smart Home OAuth2 & Fulfillment Webhook (`src/google_smarthome.py`)

**Files:**
- Create: `src/google_smarthome.py`
- Create: `tests/test_google_smarthome.py`

**Interfaces:**
- Consumes:
  - `config.GOOGLE_OAUTH_CLIENT_ID`, `config.GOOGLE_OAUTH_CLIENT_SECRET`, `config.GOOGLE_OAUTH_PIN`, `config.GOOGLE_WATCH_THRESHOLD_MINUTES`, `config.DEFAULT_SERVICE`
  - `config.resolve_user()`, `config.get_user_stops(user_key_or_name=...)`, `config.clean_alphanumeric_code(...)`
  - `red_service.format_balance_speech(...)`, `red_service.format_dual_prediction_speech(...)`, `red_service.format_travel_summary_speech(...)`, `red_service.get_stop_predictions(...)`
  - `bus_watcher.watcher_manager` (`start_watch(..., notify_channel="google_cast")`, `cancel_watch("google_home")`, `has_active_job("google_home")`)
  - `google_cast_service.speak_on_home(text)`
- Produces:
  - `google_smarthome.router` (`GET /google/oauth/auth`, `POST /google/oauth/auth`, `POST /google/oauth/token`, `POST /google/smarthome`)
  - `google_smarthome.execute_device_action(device_id: str, turn_on: bool) -> None`

- [ ] **Step 1: Write failing tests in `tests/test_google_smarthome.py`**

```python
import base64
import os
import sys
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
from src import google_smarthome
from src.bus_watcher import watcher_manager


REDIRECT_URI = "https://oauth-redirect.googleusercontent.com/r/red-movilidad-project"


@pytest.fixture
def smarthome_client(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_ID", "client-123")
    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_SECRET", "super-secret-xyz")
    monkeypatch.setattr(config, "GOOGLE_OAUTH_PIN", "2468")
    monkeypatch.setattr(config, "GOOGLE_WATCH_THRESHOLD_MINUTES", 5)

    test_app = FastAPI()
    test_app.include_router(google_smarthome.router)
    yield TestClient(test_app)
    watcher_manager.cancel_watch("google_home")


def _obtain_tokens(client: TestClient):
    res_auth = client.post(
        "/google/oauth/auth",
        data={
            "client_id": "client-123",
            "redirect_uri": REDIRECT_URI,
            "state": "state-abc",
            "pin": "2468",
        },
        follow_redirects=False,
    )
    assert res_auth.status_code == 302
    loc = res_auth.headers["location"]
    parsed = urlparse(loc)
    qs = parse_qs(parsed.query)
    assert qs["state"] == ["state-abc"]
    code = qs["code"][0]

    res_tok = client.post(
        "/google/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": "client-123",
            "client_secret": "super-secret-xyz",
        },
    )
    assert res_tok.status_code == 200
    return res_tok.json()


def test_oauth_auth_requires_server_pin_configured(smarthome_client, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_OAUTH_PIN", "")
    res = smarthome_client.get(
        "/google/oauth/auth",
        params={"client_id": "client-123", "redirect_uri": REDIRECT_URI, "state": "s1", "response_type": "code"},
    )
    assert res.status_code == 503


def test_oauth_auth_rejects_disallowed_redirect_uri(smarthome_client):
    res = smarthome_client.get(
        "/google/oauth/auth",
        params={"client_id": "client-123", "redirect_uri": "https://evil.example.com/cb", "response_type": "code"},
    )
    assert res.status_code == 400


def test_oauth_auth_wrong_pin_returns_401(smarthome_client):
    res = smarthome_client.post(
        "/google/oauth/auth",
        data={
            "client_id": "client-123",
            "redirect_uri": REDIRECT_URI,
            "state": "state-1",
            "pin": "9999",
        },
        follow_redirects=False,
    )
    assert res.status_code == 401
    assert "PIN incorrecto" in res.text


def test_oauth_full_code_and_refresh_flow_including_basic_auth(smarthome_client):
    tokens = _obtain_tokens(smarthome_client)
    assert tokens["token_type"] == "Bearer"
    assert tokens["access_token"]
    assert tokens["refresh_token"]

    basic_creds = base64.b64encode(b"client-123:super-secret-xyz").decode("ascii")
    res_ref = smarthome_client.post(
        "/google/oauth/token",
        headers={"Authorization": f"Basic {basic_creds}"},
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
        },
    )
    assert res_ref.status_code == 200
    ref_body = res_ref.json()
    assert ref_body["access_token"]
    assert ref_body["token_type"] == "Bearer"


def test_oauth_token_rejects_bad_secret_and_tampered_refresh_token(smarthome_client):
    tokens = _obtain_tokens(smarthome_client)

    res_bad_secret = smarthome_client.post(
        "/google/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": "client-123",
            "client_secret": "wrong",
        },
    )
    assert res_bad_secret.status_code == 400
    assert res_bad_secret.json()["error"] == "invalid_client"

    res_bad_tok = smarthome_client.post(
        "/google/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"] + "tamper",
            "client_id": "client-123",
            "client_secret": "super-secret-xyz",
        },
    )
    assert res_bad_tok.status_code == 400
    assert res_bad_tok.json()["error"] == "invalid_grant"


def test_smarthome_rejects_missing_or_invalid_bearer(smarthome_client):
    payload = {"requestId": "req-1", "inputs": [{"intent": "action.devices.SYNC"}]}
    assert smarthome_client.post("/google/smarthome", json=payload).status_code == 401
    assert (
        smarthome_client.post(
            "/google/smarthome",
            headers={"Authorization": "Bearer bogus.token"},
            json=payload,
        ).status_code
        == 401
    )


def test_smarthome_sync_and_query_states(smarthome_client):
    access_token = _obtain_tokens(smarthome_client)["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    res_sync = smarthome_client.post(
        "/google/smarthome",
        headers=headers,
        json={"requestId": "req-sync", "inputs": [{"intent": "action.devices.SYNC"}]},
    )
    assert res_sync.status_code == 200
    sync_payload = res_sync.json()["payload"]
    device_ids = {d["id"] for d in sync_payload["devices"]}
    assert device_ids == {"red_saldo_bip", "red_micro_habitual", "red_alcanzo_salir", "red_vigilante"}

    res_query = smarthome_client.post(
        "/google/smarthome",
        headers=headers,
        json={
            "requestId": "req-query",
            "inputs": [
                {
                    "intent": "action.devices.QUERY",
                    "payload": {
                        "devices": [
                            {"id": "red_saldo_bip"},
                            {"id": "red_vigilante"},
                            {"id": "unknown_dev"},
                        ]
                    },
                }
            ],
        },
    )
    assert res_query.status_code == 200
    q_devs = res_query.json()["payload"]["devices"]
    assert q_devs["red_saldo_bip"]["on"] is False
    assert q_devs["red_vigilante"]["on"] is False
    assert q_devs["unknown_dev"]["status"] == "ERROR"


def test_smarthome_execute_returns_immediate_success_and_dispatches_thread(smarthome_client):
    access_token = _obtain_tokens(smarthome_client)["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    started_threads = []

    class ImmediateThread:
        def __init__(self, target=None, args=(), daemon=False):
            self.target = target
            self.args = args

        def start(self):
            started_threads.append((self.target, self.args))

    with patch("src.google_smarthome.threading.Thread", ImmediateThread):
        res_exec = smarthome_client.post(
            "/google/smarthome",
            headers=headers,
            json={
                "requestId": "req-exec",
                "inputs": [
                    {
                        "intent": "action.devices.EXECUTE",
                        "payload": {
                            "commands": [
                                {
                                    "devices": [{"id": "red_micro_habitual"}, {"id": "red_vigilante"}],
                                    "execution": [{"command": "action.devices.commands.OnOff", "params": {"on": True}}],
                                }
                            ]
                        },
                    }
                ],
            },
        )

    assert res_exec.status_code == 200
    commands = res_exec.json()["payload"]["commands"]
    by_id = {c["ids"][0]: c for c in commands}
    # Momentary trigger resets UI state to False
    assert by_id["red_micro_habitual"]["states"]["on"] is False
    assert by_id["red_vigilante"]["states"]["on"] is True
    assert started_threads == [
        (google_smarthome.execute_device_action, ("red_micro_habitual", True)),
        (google_smarthome.execute_device_action, ("red_vigilante", True)),
    ]


def test_execute_device_action_runs_all_four_devices(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_WATCH_THRESHOLD_MINUTES", 5)
    sample_user = {"name": "Simón", "card": "12345678", "stop": "PD289", "service": "513"}
    sample_stops = {
        "ida": {"code": "PD289", "name": "Paradero Ida"},
        "vuelta": {"code": "PD290", "name": "Paradero Vuelta"},
        "intersection": "José Arrieta con Ictinos",
    }

    with patch("src.google_smarthome.config.resolve_user", return_value=sample_user), \
         patch("src.google_smarthome.config.get_user_stops", return_value=sample_stops), \
         patch("src.google_smarthome.google_cast_service.speak_on_home", return_value=True) as mock_cast:

        with patch("src.google_smarthome.red_service.format_balance_speech", return_value="Saldo 3000"):
            google_smarthome.execute_device_action("red_saldo_bip", True)
            mock_cast.assert_called_with("Saldo 3000")

        with patch("src.google_smarthome.red_service.format_dual_prediction_speech", return_value="513 en 4m"):
            google_smarthome.execute_device_action("red_micro_habitual", True)
            mock_cast.assert_called_with("513 en 4m")

        with patch("src.google_smarthome.red_service.format_travel_summary_speech", return_value="Resumen OK"):
            google_smarthome.execute_device_action("red_alcanzo_salir", True)
            mock_cast.assert_called_with("Resumen OK")

        # Watcher ON starts monitor when bus is > threshold
        with patch(
            "src.google_smarthome.red_service.get_stop_predictions",
            return_value={"success": True, "buses": [{"min_time": 12}]},
        ), patch.object(watcher_manager, "start_watch") as mock_start:
            google_smarthome.execute_device_action("red_vigilante", True)
            assert mock_start.called
            assert mock_start.call_args.kwargs["notify_channel"] == "google_cast"
            assert mock_start.call_args.kwargs["user_id"] == "google_home"

        # Watcher OFF cancels monitor
        with patch.object(watcher_manager, "cancel_watch", return_value=True) as mock_cancel:
            google_smarthome.execute_device_action("red_vigilante", False)
            mock_cancel.assert_called_once_with("google_home")
            assert "cancelé" in mock_cast.call_args[0][0].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_google_smarthome.py -v`
Expected: FAIL with `ImportError: cannot import name 'google_smarthome' from 'src'`

- [ ] **Step 3: Implement `src/google_smarthome.py`**

```python
import base64
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
    if not token or not secret or "." not in token:
        return None
    parts = token.split(".", 1)
    if len(parts) != 2:
        return None
    body, sig = parts
    expected_sig = _b64u_encode(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected_sig):
        return None
    try:
        payload = json.loads(_b64u_decode(body).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict) or payload.get("kind") != expected_kind:
        return None
    exp = payload.get("exp", 0)
    if exp and time.time() > exp:
        return None
    return payload


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

    form = await request.form()
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

    form = await request.form()
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
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
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
        req_devices = first_input.get("payload", {}).get("devices", [])
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
        for cmd in first_input.get("payload", {}).get("commands", []):
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_google_smarthome.py -v`
Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add src/google_smarthome.py tests/test_google_smarthome.py
git commit -m "feat: add Google Smart Home OAuth2 and webhook fulfillment"
```

---

### Task 4: FastAPI Server Wiring, Endpoint Tests & Raspberry Pi 3 Live Verification

**Files:**
- Modify: `src/local_server.py`
- Modify: `tests/test_server_endpoints.py`

**Interfaces:**
- Consumes:
  - `src.google_smarthome.router`
  - `src.google_cast_service.get_tts_clip(clip_id: str) -> Optional[bytes]`
  - `src.google_cast_service.list_cast_devices(timeout: float = 5.0) -> List[Dict[str, Any]]`
- Produces:
  - Mounted routes `/google/oauth/auth`, `/google/oauth/token`, `/google/smarthome` on `src.local_server.app`
  - `GET /api/tts/{clip_id}.mp3` -> `Response(media_type="audio/mpeg")` or HTTP `404`
  - `GET /api/cast/devices` -> `{"devices": [...]}`

- [ ] **Step 1: Write failing endpoint tests in `tests/test_server_endpoints.py`**

Append to `tests/test_server_endpoints.py`:

```python
def test_tts_clip_and_cast_devices_endpoints():
    from src import google_cast_service

    client = TestClient(app)

    assert client.get("/api/tts/nonexistent.mp3").status_code == 404

    with patch("src.google_cast_service.gTTS") as mock_gtts:
        mock_gtts.return_value.write_to_fp.side_effect = lambda fp: fp.write(b"ID3_FAKE_MP3")
        clip_id = google_cast_service.create_tts_clip("Prueba de audio")

    res_mp3 = client.get(f"/api/tts/{clip_id}.mp3")
    assert res_mp3.status_code == 200
    assert res_mp3.headers["content-type"].startswith("audio/mpeg")
    assert res_mp3.content == b"ID3_FAKE_MP3"

    with patch(
        "src.google_cast_service.list_cast_devices",
        return_value=[{"name": "Parlante Living", "cast_type": "audio"}],
    ):
        res_cast = client.get("/api/cast/devices")
    assert res_cast.status_code == 200
    assert res_cast.json() == {"devices": [{"name": "Parlante Living", "cast_type": "audio"}]}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_server_endpoints.py::test_tts_clip_and_cast_devices_endpoints -v`
Expected: FAIL with `404 Not Found` on `/api/cast/devices` (routes not wired yet).

- [ ] **Step 3: Wire router and endpoints into `src/local_server.py`**

Read `src/local_server.py` (check imports and route placement), import `HTTPException`, `Response`, `google_cast_service`, and `google_smarthome`, then add:

```python
app.include_router(google_smarthome.router)


@app.get("/api/tts/{clip_id}.mp3")
def api_tts_clip(clip_id: str):
    """Entrega el audio MP3 generado en RAM para reproducción local vía Google Cast."""
    audio = google_cast_service.get_tts_clip(clip_id)
    if audio is None:
        raise HTTPException(status_code=404, detail="TTS clip not found")
    return Response(content=audio, media_type="audio/mpeg")


@app.get("/api/cast/devices")
def api_cast_devices():
    """Lista los dispositivos Google Cast visibles en la red local para configurar GOOGLE_CAST_DEVICE."""
    return {"devices": google_cast_service.list_cast_devices()}
```

- [ ] **Step 4: Run full local `pytest` suite**

Run: `python -m pytest -v`
Expected: All existing + new tests PASS with zero failures or skipped assertions.

- [ ] **Step 5: Commit and push to `origin/master`**

```bash
git add src/local_server.py tests/test_server_endpoints.py
git commit -m "feat: wire Google Smart Home router, TTS audio route and Cast device listing"
git push origin master
```

- [ ] **Step 6: Deploy to Raspberry Pi 3 and run live verification**

1. Pull changes on Pi, install dependencies inside venv, run `pytest`, restart service:
```bash
ssh nowis@192.168.0.115 "cd /home/nowis/alexa-red-movilidad && git pull && /home/nowis/alexa-red-movilidad/venv/bin/pip install -r requirements.txt && /home/nowis/alexa-red-movilidad/venv/bin/pytest -v && systemctl --user restart alexa-red.service && systemctl --user status alexa-red.service --no-pager"
```
2. Query discovered Cast devices on Pi so user can confirm the exact speaker friendly name vs Android TV:
```bash
ssh nowis@192.168.0.115 "curl -s http://127.0.0.1:8000/api/cast/devices"
```
3. Verify external Tailscale Funnel reachability of OAuth endpoint (without changing `/` or `/alexa` existing Alexa routes):
```bash
curl -s -o /dev/null -w "%{http_code}\n" "https://nowis.tail7d0b63.ts.net/alexa/google/oauth/auth"
```
4. Walk user through adding `GOOGLE_*` variables to `/home/nowis/alexa-red-movilidad/.env`, setting Google Cloud OAuth Consent Screen to *In Production* (personal), configuring Google Home Developer Console Cloud-to-Cloud endpoints (`https://nowis.tail7d0b63.ts.net/alexa/google/...`), linking via *"Funciona con Google"*, and verifying live speaker audio without disturbing Android TV.
