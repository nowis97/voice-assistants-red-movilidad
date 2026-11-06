import time
import collections
import threading
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger("observability")

class ObservabilityStore:
    """Buffer en memoria circular (thread-safe) para registrar las últimas interacciones de Alexa."""
    def __init__(self, maxlen: int = 50):
        self._lock = threading.Lock()
        self._events: collections.deque = collections.deque(maxlen=maxlen)

    def record(
        self,
        request_type: str,
        intent_name: Optional[str] = None,
        slots: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        speech: Optional[str] = None,
        latency_ms: Optional[int] = None,
        status: str = "success",
        error_detail: Optional[str] = None
    ) -> Dict[str, Any]:
        """Registra un evento de interacción con timestamp y metadatos."""
        # Enmascarar User ID para privacidad
        masked_user = user_id[-8:] if user_id and len(user_id) > 8 else (user_id or "anónimo")

        event = {
            "id": int(time.time() * 1000),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_type": request_type,
            "intent_name": intent_name or request_type,
            "slots": slots or {},
            "user_id": masked_user,
            "speech": speech or "",
            "latency_ms": latency_ms or 0,
            "status": status,
            "error_detail": error_detail
        }

        with self._lock:
            self._events.appendleft(event)

        return event

    def get_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retorna los eventos más recientes en orden cronológico descendente."""
        with self._lock:
            return list(self._events)[:limit]

    def clear(self) -> None:
        """Limpia el historial de eventos."""
        with self._lock:
            self._events.clear()


# Instancia global compartida en el servidor
store = ObservabilityStore(maxlen=50)
