# Bus Watcher & Alexa Reminders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the "Modo Vigilante" feature: allow users to ask Alexa to monitor a bus line in background and automatically trigger a spoken Alexa Reminder (*«Recordatorio de Red Movilidad: Tu micro 513 está a 4 minutos...»*) when the bus is within their requested time threshold (default 5 min).

**Architecture:** A lightweight in-memory async background worker (`src/bus_watcher.py`) polls DTPM predictive stop arrivals every 25 seconds on the Raspberry Pi 3. When arrival time $\le$ threshold, it calls the official Alexa Reminders API (`POST /v1/alerts/reminders`) using the session's bearer token. Handlers in `src/alexa_handlers.py` manage `WatchBusIntent`, `CancelWatchIntent`, and reminder permission requests. Active watcher status and manual web cancellation are exposed in `src/local_server.py` and the real-time `/dashboard`.

**Tech Stack:** Python 3.11+, FastAPI, `ask-sdk-core`, `ask-sdk-model`, Requests, Pytest, ASK CLI, systemd.

**Spec:** `docs/superpowers/specs/2026-11-09-bus-watcher-reminders-design.md`

## Global Constraints
- Preserve backward compatibility for all existing intents (`RouteToDestinationIntent`, `PrediccionMicroIntent`, `SaldoBipIntent`, `GuardarPreferenciaIntent`).
- Stop codes must always be pronounced phonetically (`P D 289`).
- Alexa Reminders API requires permission `alexa::alerts:reminders:skill:readwrite` in `skill.json`.
- Polling loop must run asynchronously without blocking FastAPI or uvicorn web threads.
- Safety timeout: background watcher jobs must automatically terminate after 30 minutes.
- Every task must carry its own failing test, minimal implementation, passing test, and git commit.

---

### Task 1: Alexa Reminders API Client & Service

**Files:**
- Create: `src/reminders_service.py`
- Test: `tests/test_reminders_service.py`

**Interfaces:**
- Produces:
  - `create_spoken_reminder(api_endpoint: str, api_access_token: str, text: str, locale: str = "es-US") -> Dict[str, Any]`:
    Calls `POST {api_endpoint}/v1/alerts/reminders` with `SCHEDULED_RELATIVE` offset 0 and spoken text.
  - `has_reminder_permission(handler_input: Any) -> bool`:
    Checks if `handler_input.request_envelope.context.system.user.permissions.consent_token` or API access token is valid for reminders.

- [ ] **Step 1: Write failing test in `tests/test_reminders_service.py`**

```python
import pytest
from unittest.mock import patch, MagicMock

def test_create_spoken_reminder_success():
    from src.reminders_service import create_spoken_reminder
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"alertToken": "amzn1.reminder.test"}

    with patch("requests.post", return_value=mock_resp) as mock_post:
        res = create_spoken_reminder(
            api_endpoint="https://api.amazonalexa.com",
            api_access_token="test_token",
            text="Tu micro 513 está a 4 minutos",
            locale="es-US"
        )
        assert res["success"] is True
        assert res["alert_token"] == "amzn1.reminder.test"
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://api.amazonalexa.com/v1/alerts/reminders"
        assert kwargs["headers"]["Authorization"] == "Bearer test_token"
        payload = kwargs["json"]
        assert payload["trigger"]["type"] == "SCHEDULED_RELATIVE"
        assert payload["trigger"]["offsetInSeconds"] == 0
        assert payload["alertInfo"]["spokenInfo"]["content"][0]["text"] == "Tu micro 513 está a 4 minutos"


def test_create_spoken_reminder_unauthorized():
    from src.reminders_service import create_spoken_reminder
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.json.return_value = {"message": "Unauthorized"}

    with patch("requests.post", return_value=mock_resp):
        res = create_spoken_reminder(
            api_endpoint="https://api.amazonalexa.com",
            api_access_token="invalid_token",
            text="Tu micro viene",
            locale="es-US"
        )
        assert res["success"] is False
        assert "403" in res["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_reminders_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.reminders_service'`

- [ ] **Step 3: Implement `src/reminders_service.py`**

```python
import logging
import requests
from datetime import datetime, timezone
from typing import Dict, Any

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 6

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
    clean_endpoint = api_endpoint.rstrip("/")
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_reminders_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/reminders_service.py tests/test_reminders_service.py
git commit -m "feat: implement Alexa Reminders API client"
```

---

### Task 2: Bus Watcher Background Subsystem

**Files:**
- Create: `src/bus_watcher.py`
- Test: `tests/test_bus_watcher.py`

**Interfaces:**
- Consumes: `red_service.get_stop_predictions`, `reminders_service.create_spoken_reminder`, `observability.store`
- Produces:
  - `WatcherJob` dataclass.
  - `watcher_manager`:
    - `start_watch(user_id, linea, stop_code, corner_name, threshold_minutes, api_endpoint, api_access_token) -> WatcherJob`
    - `cancel_watch(user_id) -> bool`
    - `get_active_jobs() -> List[Dict[str, Any]]`

- [ ] **Step 1: Write failing test in `tests/test_bus_watcher.py`**

```python
import pytest
import time
from unittest.mock import patch, MagicMock
from src.bus_watcher import BusWatcherManager

def test_bus_watcher_start_and_cancel():
    manager = BusWatcherManager(poll_interval_seconds=1)
    job = manager.start_watch(
        user_id="user_123",
        linea="513",
        stop_code="PD289",
        corner_name="José Arrieta con Ictinos",
        threshold_minutes=5,
        api_endpoint="https://api.amazonalexa.com",
        api_access_token="token_abc"
    )
    assert job.user_id == "user_123"
    assert job.linea == "513"
    assert job.threshold_minutes == 5
    assert manager.has_active_job("user_123") is True

    cancelled = manager.cancel_watch("user_123")
    assert cancelled is True
    assert manager.has_active_job("user_123") is False


def test_bus_watcher_triggers_reminder_when_in_range():
    manager = BusWatcherManager(poll_interval_seconds=0.1)

    mock_pred = {
        "success": True,
        "buses": [
            {"service": "513", "min_time": 4, "max_time": 4, "meters": 800}
        ]
    }

    with patch("src.red_service.get_stop_predictions", return_value=mock_pred), \
         patch("src.reminders_service.create_spoken_reminder", return_value={"success": True}) as mock_remind:
        
        job = manager.start_watch(
            user_id="user_456",
            linea="513",
            stop_code="PD289",
            corner_name="José Arrieta con Ictinos",
            threshold_minutes=5,
            api_endpoint="https://api.amazonalexa.com",
            api_access_token="token_xyz"
        )

        # Dar tiempo a que el loop ejecute al menos un chequeo
        time.sleep(0.3)
        assert mock_remind.called
        assert manager.has_active_job("user_456") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_bus_watcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.bus_watcher'`

- [ ] **Step 3: Implement `src/bus_watcher.py`**

```python
import time
import threading
import logging
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional

from src import red_service
from src import reminders_service
from src import observability

logger = logging.getLogger("bus_watcher")

SAFETY_TIMEOUT_SECONDS = 1800  # 30 minutos

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


class BusWatcherManager:
    """Administra las tareas de vigilancia en segundo plano para usuarios de Alexa."""
    def __init__(self, poll_interval_seconds: float = 25.0):
        self._lock = threading.Lock()
        self._jobs: Dict[str, WatcherJob] = {}  # user_id -> WatcherJob
        self._threads: Dict[str, threading.Thread] = {}
        self._poll_interval = poll_interval_seconds

    def has_active_job(self, user_id: str) -> bool:
        with self._lock:
            return user_id in self._jobs and self._jobs[user_id].status == "active"

    def get_job(self, user_id: str) -> Optional[WatcherJob]:
        with self._lock:
            return self._jobs.get(user_id)

    def get_active_jobs(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [asdict(j) for j in self._jobs.values() if j.status == "active"]

    def cancel_watch(self, user_id: str) -> bool:
        with self._lock:
            if user_id in self._jobs and self._jobs[user_id].status == "active":
                self._jobs[user_id].status = "cancelled"
                del self._jobs[user_id]
                logger.info(f"Vigilancia cancelada para usuario {user_id[-8:]}")
                return True
        return False

    def start_watch(
        self,
        user_id: str,
        linea: str,
        stop_code: str,
        corner_name: str,
        threshold_minutes: int,
        api_endpoint: str,
        api_access_token: str
    ) -> WatcherJob:
        # Cancelar cualquier trabajo previo del usuario
        self.cancel_watch(user_id)

        clean_linea = linea.strip().upper()
        clean_stop = stop_code.strip().upper()
        job_id = f"job_{int(time.time()*1000)}"

        job = WatcherJob(
            job_id=job_id,
            user_id=user_id,
            linea=clean_linea,
            stop_code=clean_stop,
            corner_name=corner_name,
            threshold_minutes=threshold_minutes,
            api_endpoint=api_endpoint,
            api_access_token=api_access_token,
            created_at=time.time()
        )

        with self._lock:
            self._jobs[user_id] = job

        # Iniciar hilo de vigilancia independiente
        t = threading.Thread(target=self._worker_loop, args=(job,), daemon=True)
        self._threads[user_id] = t
        t.start()

        logger.info(f"Vigilancia iniciada: {clean_linea} en {clean_stop} (umbral: {threshold_minutes} min)")
        return job

    def _worker_loop(self, job: WatcherJob) -> None:
        user_id = job.user_id
        consecutive_errors = 0

        while True:
            # 1. Chequeo de cancelación o timeout
            with self._lock:
                if user_id not in self._jobs or self._jobs[user_id].job_id != job.job_id:
                    break
                if job.status != "active":
                    break
                if (time.time() - job.created_at) > SAFETY_TIMEOUT_SECONDS:
                    logger.info(f"Vigilancia {job.job_id} terminada por timeout de 30 min")
                    job.status = "timeout"
                    del self._jobs[user_id]
                    break

            # 2. Consultar predictivo de paradero
            try:
                pred = red_service.get_stop_predictions(job.stop_code, job.linea)
                job.checks_count += 1

                if pred["success"] and pred["buses"]:
                    consecutive_errors = 0
                    first_bus = pred["buses"][0]
                    min_time = first_bus.get("min_time", 0)
                    job.last_eta_minutes = min_time

                    # 3. Evaluar umbral de aviso
                    if min_time <= job.threshold_minutes:
                        logger.info(f"¡Micro {job.linea} en rango ({min_time} <= {job.threshold_minutes} min)! Disparando recordatorio...")
                        spoken_text = (
                            f"Tu micro {job.linea} está a {min_time} minutos de tu esquina "
                            f"en {job.corner_name}, es hora de salir."
                        )
                        reminders_service.create_spoken_reminder(
                            api_endpoint=job.api_endpoint,
                            api_access_token=job.api_access_token,
                            text=spoken_text
                        )
                        # Registrar en observabilidad
                        observability.store.record(
                            request_type="WatcherTriggered",
                            intent_name=f"Alerta: {job.linea} en camino",
                            slots={"linea": job.linea, "eta": min_time, "paradero": job.stop_code},
                            user_id=job.user_id,
                            speech=spoken_text,
                            status="success"
                        )
                        with self._lock:
                            job.status = "triggered"
                            if user_id in self._jobs:
                                del self._jobs[user_id]
                        break
                else:
                    job.last_eta_minutes = None
            except Exception as e:
                consecutive_errors += 1
                logger.warning(f"Error en chequeo de vigilancia {job.job_id}: {e}")
                if consecutive_errors >= 5:
                    logger.error(f"Demasiados fallos consecutivos en vigilancia {job.job_id}. Deteniendo.")
                    with self._lock:
                        job.status = "error"
                        if user_id in self._jobs:
                            del self._jobs[user_id]
                    break

            time.sleep(self._poll_interval)


# Instancia singleton del gestor de vigilancia
watcher_manager = BusWatcherManager()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_bus_watcher.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/bus_watcher.py tests/test_bus_watcher.py
git commit -m "feat: implement bus watcher background loop manager"
```

---

### Task 3: Alexa Handlers & Manifest Permissions Update

**Files:**
- Modify: `src/alexa_handlers.py`
- Modify: `src/lambda_function.py`
- Modify: `skill-package/skill.json`
- Modify: `skill-package/interactionModels/custom/es-US.json`
- Modify: `skill-package/interactionModels/custom/es-ES.json`
- Modify: `skill-package/interactionModels/custom/es-MX.json`
- Test: `tests/test_handlers.py`

**Interfaces:**
- Implements:
  - `WatchBusIntentHandler`: handles `WatchBusIntent`. Requests reminder permission if missing, checks current arrival time (alerts immediately if already $\le$ threshold), or starts `watcher_manager.start_watch`.
  - `CancelWatchIntentHandler`: handles `CancelWatchIntent`. Cancels active watcher job.

- [ ] **Step 1: Write failing test in `tests/test_handlers.py`**

```python
def test_watch_bus_intent_handler_without_permission():
    from src.alexa_handlers import WatchBusIntentHandler
    from ask_sdk_core.handler_input import HandlerInput
    from ask_sdk_model import RequestEnvelope, IntentRequest, Intent, Slot, Context, System, User

    req = IntentRequest(
        intent=Intent(
            name="WatchBusIntent",
            slots={"linea": Slot(name="linea", value="513")}
        )
    )
    # Contexto sin apiAccessToken
    context = Context(system=System(user=User(user_id="user_test_no_perm")))
    handler_input = HandlerInput(request_envelope=RequestEnvelope(request=req, context=context))

    handler = WatchBusIntentHandler()
    assert handler.can_handle(handler_input) is True
    res = handler.handle(handler_input)
    assert "permiso" in res.output_speech.ssml.lower()


def test_cancel_watch_intent_handler():
    from src.alexa_handlers import CancelWatchIntentHandler
    from src.bus_watcher import watcher_manager
    from ask_sdk_core.handler_input import HandlerInput
    from ask_sdk_model import RequestEnvelope, IntentRequest, Intent, Context, System, User

    watcher_manager.start_watch("user_cancel_test", "513", "PD289", "José Arrieta", 5, "http://api", "token")
    assert watcher_manager.has_active_job("user_cancel_test") is True

    req = IntentRequest(intent=Intent(name="CancelWatchIntent"))
    context = Context(system=System(user=User(user_id="user_cancel_test")))
    handler_input = HandlerInput(request_envelope=RequestEnvelope(request=req, context=context))

    handler = CancelWatchIntentHandler()
    assert handler.can_handle(handler_input) is True
    res = handler.handle(handler_input)
    assert "cancel" in res.output_speech.ssml.lower()
    assert watcher_manager.has_active_job("user_cancel_test") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_handlers.py -k "Watch" -v`
Expected: FAIL with `ImportError: cannot import name 'WatchBusIntentHandler'`

- [ ] **Step 3: Implement handlers in `src/alexa_handlers.py` & register in `src/lambda_function.py`**

Add `WatchBusIntentHandler` and `CancelWatchIntentHandler`.
In `skill-package/skill.json`, add:
```json
{
  "name": "alexa::alerts:reminders:skill:readwrite"
}
```
In `skill-package/interactionModels/custom/es-US.json`, `es-ES.json`, `es-MX.json`:
Add `WatchBusIntent` and `CancelWatchIntent`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_handlers.py -k "Watch" -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/alexa_handlers.py src/lambda_function.py skill-package/ tests/test_handlers.py
git commit -m "feat: add WatchBusIntentHandler, CancelWatchIntentHandler and permissions"
```

---

### Task 4: Dashboard Integration & Watcher Status Endpoints

**Files:**
- Modify: `src/local_server.py`
- Test: `tests/test_observability.py`

**Interfaces:**
- Adds:
  - `GET /api/watcher/active`: returns list of active watcher jobs.
  - `POST /api/watcher/cancel`: cancels watcher job by user_id.
  - Live HTML panel in `/dashboard` showing active watcher cards with realtime countdown and cancel button.

- [ ] **Step 1: Write failing test in `tests/test_observability.py`**

```python
def test_dashboard_watcher_api_endpoints():
    from src.bus_watcher import watcher_manager
    from fastapi.testclient import TestClient
    from src.local_server import app

    watcher_manager.start_watch("test_user_dash", "513", "PD289", "José Arrieta", 5, "http://api", "tok")

    client = TestClient(app)
    res = client.get("/api/watcher/active")
    assert res.status_code == 200
    jobs = res.json()
    assert len(jobs) >= 1
    assert any(j["linea"] == "513" for j in jobs)

    res_cancel = client.post("/api/watcher/cancel?user_id=test_user_dash")
    assert res_cancel.status_code == 200
    assert res_cancel.json()["status"] == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_observability.py -k "watcher_api" -v`
Expected: FAIL with `404 Not Found`

- [ ] **Step 3: Implement endpoints and UI panel in `src/local_server.py`**

Add endpoints `/api/watcher/active` and `/api/watcher/cancel`.
Add HTML card section in `/dashboard` dynamically rendering active watcher jobs.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_observability.py -k "watcher_api" -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/local_server.py tests/test_observability.py
git commit -m "feat: add live bus watcher dashboard panel and cancel endpoint"
```

---

### Task 5: End-to-End Verification, Deployment to Raspberry Pi & CI/CD Sync

**Files:**
- None (Deployment & Verification)

- [ ] **Step 1: Run full test suite with coverage**

Run: `python -m pytest tests/ -v`
Expected: 100% tests passing (60+ tests).

- [ ] **Step 2: Deploy updated code to Raspberry Pi 3**

Copy `src/`, `tests/`, `skill-package/` to `nowis@192.168.0.115:/home/nowis/alexa-red-movilidad/`.
Restart `alexa-red.service`: `systemctl --user restart alexa-red.service`.
Verify `systemctl --user status alexa-red.service`.

- [ ] **Step 3: Push to GitHub to trigger CI/CD**

Run: `git push origin master`
Trigger `deploy-skill.yml` workflow and verify models and permissions deploy to Alexa Developer Console.

- [ ] **Step 4: Live Verification**

Test `/dashboard` and simulated intent against live Tailscale endpoint.
