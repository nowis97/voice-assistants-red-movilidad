import time
import threading
import logging
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional

from src import red_service
from src import reminders_service

try:
    from src import google_cast_service
except ImportError:
    import google_cast_service

logger = logging.getLogger("bus_watcher")

SAFETY_TIMEOUT_SECONDS = 1800  # 30 minutos de tiempo máximo de vigilancia


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
                logger.info(f"Vigilancia cancelada para usuario {user_id[-8:] if len(user_id) >= 8 else user_id}")
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
        api_access_token: str,
        notify_channel: str = "alexa"
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
            created_at=time.time(),
            notify_channel=notify_channel
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

                if pred.get("success") and pred.get("buses"):
                    consecutive_errors = 0
                    first_bus = pred["buses"][0]
                    min_time = first_bus.get("min_time", 0)
                    job.last_eta_minutes = min_time

                    logger.info(
                        f"[bus_watcher] Chequeo #{job.checks_count} | Job: {job.job_id} | "
                        f"Micro: {job.linea} en {job.stop_code} | ETA: {min_time} min (Umbral: {job.threshold_minutes} min)"
                    )

                    # 3. Evaluar umbral de aviso
                    if min_time <= job.threshold_minutes:
                        logger.info(
                            f"[bus_watcher] ¡ALERTA DISPARADA! Micro {job.linea} a {min_time} min "
                            f"(<= {job.threshold_minutes} min)."
                        )
                        spoken_text = (
                            f"Tu micro {job.linea} está a {min_time} minutos de tu esquina "
                            f"en {job.corner_name}, es hora de salir."
                        )
                        if job.notify_channel == "google_cast":
                            try:
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
                            except Exception as e:
                                logger.error(
                                    f"[Watcher {job.job_id}] Falló entrega de aviso Google Cast: {e}",
                                    exc_info=True
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
                        with self._lock:
                            job.status = "triggered"
                            if user_id in self._jobs:
                                del self._jobs[user_id]
                        break
                else:
                    job.last_eta_minutes = None
                    logger.info(
                        f"[bus_watcher] Chequeo #{job.checks_count} | Job: {job.job_id} | "
                        f"Micro: {job.linea} en {job.stop_code} | Sin predictivo disponible aún (esperando {self._poll_interval}s)"
                    )
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
