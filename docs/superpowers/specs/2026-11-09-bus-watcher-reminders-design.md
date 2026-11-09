# Especificación de Diseño: Modo Vigilante (Seguimiento Continuo y Recordatorios de Salida)

## 1. Resumen Ejecutivo y Objetivos

Permitir que los usuarios soliciten a Alexa vigilar una micro específica en su paradero habitual (por ejemplo, *«Alexa, dile a Red Movilidad que vigile la 513»* o *«avísame cuando la 513 esté a 8 minutos»*).
El sistema en la Raspberry Pi 3 monitorea en segundo plano el arribo del bus cada 25 segundos y, cuando el tiempo estimado de llegada es menor o igual al umbral solicitado (por defecto 5 minutos), dispara automáticamente un **Recordatorio de Voz de Alexa (Alexa Reminders API)**:
> *«Recordatorio de Red Movilidad: Tu micro 513 está a 4 minutos de tu esquina en José Arrieta, es momento de salir.»*

El usuario no necesita mantener la skill abierta ni mirar su teléfono; Alexa emite un timbre sonoro y habla en voz alta en el momento preciso.

---

## 2. Arquitectura del Sistema

```mermaid
flowchart TD
    User([Usuario]) -->|1. 'Vigila la 513'| Alexa[Parlante Echo / Alexa]
    Alexa --> Webhook[FastAPI / Local Server]
    Webhook --> WatchHandler[WatchBusIntentHandler]
    
    WatchHandler --> PermCheck{¿Tiene permiso\nReminders?}
    PermCheck -- No --> AskPerm[Enviar tarjeta de consentimiento\ny pedir permiso por voz]
    PermCheck -- Sí --> StartWatch[Registrar Job en BusWatcher]
    
    StartWatch --> ConfirmSpeech[Alexa confirma de inmediato:\n'Vigilaré la 513 y te avisaré...']
    ConfirmSpeech --> User
    
    subgraph BackgroundWorker[Worker Asíncrono en Raspberry Pi]
        StartWatch --> WatcherLoop[Bucle de Monitoreo cada 25s]
        WatcherLoop --> XORAPI[GET api.xor.cl/red/bus-stop/{stop}]
        XORAPI --> CheckETA{¿ETA <= Umbral\n(ej. 5 min)?}
        CheckETA -- No --> Sleep25[Esperar 25s y repetir]
        Sleep25 --> WatcherLoop
        CheckETA -- Sí --> FireReminder[Disparar Alexa Reminder]
    end
    
    FireReminder --> AlexaAPI[POST /v1/alerts/reminders]
    AlexaAPI --> AlexaDevice[Parlante Echo suena y habla]
    AlexaDevice -->|2. Alarma de salida| User
    
    WatcherLoop --> Dashboard[Dashboard Web /dashboard:\nEstado del Vigilante en Vivo]
```

---

## 3. Integración con Alexa Reminders API

### 3.1. Permisos en `skill.json`
- Se agrega el scope oficial de recordatorios:
  ```json
  {
    "name": "alexa::alerts:reminders:skill:readwrite"
  }
  ```

### 3.2. Verificación y Tarjeta de Consentimiento
- Si la solicitud no contiene permisos concedidos por el usuario, el handler devuelve una directiva de solicitud de permisos (`AskForPermissionsConsentDirective`):
  - **Texto hablado:** *«Para avisarte en voz alta cuando venga la micro, necesito permiso para crear recordatorios. Te envié una tarjeta a la aplicación de Alexa para activarlo con un toque.»*
  - **Card:** Tarjeta de permisos en la aplicación Alexa para activación en un clic.

### 3.3. Creación del Recordatorio Instantáneo
- **Endpoint:** `{api_endpoint}/v1/alerts/reminders`
- **Headers:**
  - `Authorization: Bearer {api_access_token}`
  - `Content-Type: application/json`
- **Payload:**
  ```json
  {
    "requestTime": "2026-11-09T02:30:00Z",
    "trigger": {
      "type": "SCHEDULED_RELATIVE",
      "offsetInSeconds": 0
    },
    "alertInfo": {
      "spokenInfo": {
        "content": [{
          "locale": "es-US",
          "text": "Tu micro {linea} está a {minutos} minutos de tu esquina en {esquina}, es hora de salir."
        }]
      }
    },
    "pushNotification": {
      "status": "ENABLED"
    }
  }
  ```

---

## 4. Subsistema `BusWatcher` (`src/bus_watcher.py`)

### 4.1. Estructura de Datos del Trabajo (`WatcherJob`)
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
    status: str = "active"  # "active", "triggered", "cancelled", "timeout"
```

### 4.2. Ciclo de Vida del Monitoreo
1. **Inicio:**
   - Si el usuario ya tiene un trabajo activo, se cancela el anterior y se reemplaza por el nuevo.
   - Chequeo preliminar: Si el bus ya está a $\le$ minutos pedidos al momento de iniciar, se responde de inmediato sin crear el trabajo.
2. **Bucle de Monitoreo (cada 25 segundos):**
   - Consulta `get_stop_predictions(stop_code, service=linea)`.
   - Extrae el menor tiempo de arribo (`min_time`).
   - Actualiza métricas del trabajo (`last_eta_minutes`, `checks_count`).
   - Si `min_time <= threshold_minutes`:
     - Llama a la API de Recordatorios de Alexa.
     - Marca el trabajo como `triggered` y lo remueve.
3. **Cancelación Manual (`CancelWatchIntent`):**
   - Cancela el trabajo activo del usuario y responde: *«Listo, cancelé la vigilancia de la micro.»*
4. **Timeout de Seguridad:**
   - Si transcurren 30 minutos sin alcanzar el umbral, el trabajo pasa a `timeout` y se destruye automáticamente.

---

## 5. Diseño de Interacción de Voz (VUI)

### 5.1. Intents y Slots
- **`WatchBusIntent`**:
  - `linea` (Tipo: `AMAZON.SearchQuery` o `lineaType`)
  - `minutos` (Tipo: `AMAZON.NUMBER`, opcional, por defecto 5)
  - `sentido` (Tipo: `SentidoType`, opcional, "ida" / "vuelta")
- **`CancelWatchIntent`**:
  - Sin slots.

### 5.2. Frases de Muestra (Utterances)
- *«vigila la {linea}»*
- *«vigila la {linea} de ida»*
- *«vigila la {linea} de vuelta»*
- *«avísame cuando la {linea} esté a {minutos} minutos»*
- *«avísame cuando venga la {linea}»*
- *«avísame cuando la {linea} esté cerca»*
- *«monitorea la {linea}»*
- *«cancela la vigilancia»*
- *«cancela el aviso»*
- *«deja de vigilar la micro»*

### 5.3. Pronunciación y Respuestas
- **Confirmación:**
  > *«Entendido, Simón. Vigilaré la 513 en tu paradero P D 289 y te avisaré cuando esté a 5 minutos.»*
- **Alerta de salida inmediata (si ya está encima):**
  > *«Ojo, la 513 ya está a solo 2 minutos de tu paradero P D 289. Tienes que salir ahora mismo.»*
- **Cancelación:**
  > *«Listo, cancelé la vigilancia de la micro.»*

---

## 6. Integración con el Dashboard de Observabilidad

El endpoint `/api/watcher/status` y la página `/dashboard` incluirán:
- **Panel "Micros en Vigilancia Activa"**:
  - Línea y paradero monitoreado.
  - Umbral configurado.
  - Último ETA reportado por el DTPM.
  - Contador de chequeos y tiempo transcurrido.
  - Botón web para **"Cancelar vigilancia"**.

---

## 7. Plan de Pruebas y Validación

1. **Pruebas Unitarias (`tests/test_bus_watcher.py`):**
   - Creación, actualización y cancelación de `WatcherJob`.
   - Evaluación de umbral ($\le$ 5 min).
   - Mock de llamada a Alexa Reminders API (`POST /v1/alerts/reminders`).
   - Timeout de seguridad a los 30 minutos.
2. **Pruebas de Handlers (`tests/test_handlers.py`):**
   - `WatchBusIntentHandler` con y sin permisos de recordatorio.
   - `CancelWatchIntentHandler`.
3. **Pruebas en la Raspberry Pi 3:**
   - Ejecución del bucle asíncrono sin bloqueo de peticiones web.
   - Verificación de consumo de CPU/RAM.
4. **Despliegue CI/CD:**
   - Actualización de `skill.json` con permisos de recordatorios y modelos en `es-US`, `es-ES`, `es-MX`.
