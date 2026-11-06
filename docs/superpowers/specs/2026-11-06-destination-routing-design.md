# Especificación de Diseño: Enrutamiento a Destino y Micros en Tiempo Real

## 1. Resumen Ejecutivo y Objetivos

Permitir que los usuarios soliciten a Alexa indicaciones para llegar a un destino en el Gran Santiago (por ejemplo, *«¿Qué micros me sirven para ir a Providencia con Pedro de Valdivia?»* o *«¿Cómo llego a Avenida Grecia 1234?»*).
Alexa responderá de forma concisa y natural indicando:
1. Las líneas de micro que sirven la ruta (directas o con transbordo).
2. El paradero exacto de subida más conveniente con su distancia peatonal.
3. El tiempo de espera en vivo para la llegada del bus (*«le faltan 4 minutos»*).
4. El tiempo estimado total de viaje.

---

## 2. Arquitectura del Sistema

```mermaid
flowchart TD
    User([Usuario]) -->|Pide ruta| Alexa[Alexa Skill: RouteToDestinationIntent]
    Alexa --> Webhook[Flask Local Server / AWS Lambda]
    Webhook --> IntentHandler[RouteToDestinationIntentHandler]
    
    IntentHandler --> LocService[src/location_service.py]
    LocService -->|1. Origen| UserConfig[users.json / stops.db / GPS]
    LocService -->|2. Destino| Nominatim[OpenStreetMap Nominatim]
    
    IntentHandler --> RedService[src/red_service.py]
    RedService -->|3. Planificar Ruta| RedPlannerAPI[Red Movilidad: /phone/v13/routeplanner/calculate]
    RedPlannerAPI -->|Itinerarios| RedService
    
    RedService -->|4. Predictivo En Vivo| XorAPI[api.xor.cl/red/bus-stop/{stop_code}]
    XorAPI -->|Tiempos ETA| RedService
    
    RedService --> Formatter[Speech Formatter]
    Formatter -->|Pronunciación 'P D 184'| Alexa
    Alexa -->|Respuesta de Voz| User
```

---

## 3. Integraciones de APIs y Servicios

### 3.1. Planificador Multimodal Oficial de Red Movilidad
- **Endpoint:** `GET https://appred.tstgo.cl/phone/v13/routeplanner/calculate`
- **Headers:** `RED_HEADERS` (`User-Agent: okhttp/4.9.0`, `Os-Type: Android`, `App-Version: 5.18.6`, `Phone-Id: 9d756ff1-bd35-4edb-96df-ecbda9843022`)
- **Parámetros:**
  - `origin`: Coordenadas en formato `"{lat},{lon}"` (ej. `"-33.4578,-70.5891"`).
  - `destination`: Coordenadas en formato `"{lat},{lon}"` (ej. `"-33.4225,-70.6094"`).
- **Respuesta:** Lista de itinerarios multimodales conteniendo:
  - `duration`: Tiempo total en segundos.
  - `transfers`: Cantidad de transbordos (0 = directo, 1 = 1 combinación).
  - `legs`: Tramos del viaje (caminata `WALK`, transporte `BUS` o `SUBWAY`).
    - Para `BUS`: `route` (ej. `"513"`), `from.stopId` (ej. `"PD184"`), `from.name`, `to.stopId`, `to.name`.
    - Para `SUBWAY`: `route` (ej. `"L4"`), `from.name` (estación subida), `to.name` (estación bajada).

### 3.2. Geocodificación de Destino
- **Servicio:** `geocode_address` en `src/location_service.py`.
- **Lógica de normalización:**
  - Detecta esquinas conectadas por *"con"*, *"y"*, *"esquina"* (ej. *"Grecia con Salvador"*) y las convierte a `"Grecia / Salvador, Santiago, Chile"` para Nominatim.
  - Si el usuario menciona una estación de Metro o hito (ej. *"Metro Tobalaba"*), se geocodifica directamente contra Santiago, Chile.
  - Fallback a `stops.db` si el texto coincide con un código de paradero (ej. `"PD184"`) o un nombre de estación de Metro.

### 3.3. Tiempos de Llegada en Tiempo Real (Predictivo)
- **Servicio:** `get_stop_predictions(stop_code, service)` en `src/red_service.py` vía `api.xor.cl`.
- **Propósito:** Hidratar la primera micro a abordar con los minutos reales que faltan para su llegada al paradero.

---

## 4. Lógica de Enrutamiento y Selección de Alternativas

1. **Priorización de Rutas Directas (`transfers == 0`):**
   - Si existen itinerarios directos, se seleccionan los buses correspondientes.
   - Si más de una línea directa sirve el trayecto desde el paradero más cercano, se mencionan (ej. *"te sirven la 104 y la 212"*).
2. **Manejo de Transbordos (`transfers >= 1`):**
   - Si no hay servicio directo, se escoge el itinerario con menor duración total.
   - Se describe el primer bus y su paradero, el punto de transbordo (paradero o estación) y la segunda combinación (bus o línea de Metro).
3. **Punto de Partida (Origen):**
   - Si el usuario dice *"desde X hasta Y"*, se geocodifica el origen X.
   - De lo contrario, se utilizan las coordenadas de su paradero habitual guardado (`ida` o `vuelta` en `users.json`), o GPS/Echo Device Address si está disponible.

---

## 5. Diseño de Interacción de Voz (Alexa VUI)

### 5.1. Intent y Slots
- **Intent:** `RouteToDestinationIntent`
- **Slots:**
  - `Destination` (Tipo: `AMAZON.SearchQuery`): Captura la dirección, esquina o hito destino.
  - `Origin` (Tipo: `AMAZON.SearchQuery`, opcional): Captura el origen explícito si el usuario lo menciona.
- **Frases de Ejemplo (Utterances):**
  - *«qué micros me sirven para ir a {Destination}»*
  - *«qué micro me sirve para ir a {Destination}»*
  - *«cómo llego a {Destination}»*
  - *«cómo me voy a {Destination}»*
  - *«qué micro tomo para {Destination}»*
  - *«dime la ruta para ir a {Destination}»*
  - *«cómo llego desde {Origin} hasta {Destination}»*

### 5.2. Reglas de Pronunciación y Fonética
- **Códigos de Paradero:**
  - Letras separadas y número entero: `PD184` se convierte en `P D 184` para que Alexa pronuncie: **«P D ciento ochenta y cuatro»**.
  - Evita trabalenguas como *"pedeciento ochenta y cuatro"*.
- **Abreviaturas Viales:**
  - `clean_intersection_name`: Transforma `"Av. Grecia / Esq. Salvador"` en `"Avenida Grecia con Salvador"`.
  - Transforma `"(M)"` en `"Metro"`.

### 5.3. Ejemplos de Respuesta Hablada
- **Ruta Directa:**
  > *«Para ir a Pedro de Valdivia con Providencia, te sirve la 513 en tu paradero P D 184, a 120 metros. La micro viene en 4 minutos y el viaje toma unos 25 minutos.»*
- **Ruta con Transbordo:**
  > *«Para ir a Vitacura con Alonso de Córdova no hay micro directa desde tu esquina. Te sugiero tomar la 506 en tu paradero P D 184, que viene en 5 minutos, bajarte en Plaza Italia y combinar con la 405. El viaje total toma unos 38 minutos.»*
- **Ruta con Metro:**
  > *«Para ir a Manquehue, te sugiero tomar la 506 en tu paradero P D 184 que viene en 3 minutos hasta Metro Grecia, y ahí combinar en la Línea 4. Llegarás en unos 30 minutos.»*

---

## 6. Manejo de Errores y Casos Límite

1. **Destino no encontrado:**
   > *«No pude encontrar esa dirección o esquina. Por favor intenta diciendo la calle principal y una intersección, por ejemplo: Providencia con Pedro de Valdivia.»*
2. **Destino a corta distancia a pie (< 200m):**
   > *«Ese destino está a solo una cuadra de donde te encuentras, puedes llegar caminando en unos dos minutos.»*
3. **Micro válida pero sin buses en ruta (horario nocturno):**
   > *«Para ir a Apoquindo te sirve la 401 en tu paradero P C 153, pero no hay buses en recorrido en este momento.»*
4. **Fallo o timeout en la API de Red:**
   > *«El servicio de rutas de Red Movilidad no responde en este momento. Por favor intenta de nuevo en un minuto.»*
5. **Usuario sin paradero guardado ni ubicación:**
   > *«Para saber qué micro te sirve, primero necesito saber desde dónde sales. Puedes decirme: guarda mi paradero de ida.»*

---

## 7. Plan de Pruebas y Verificación

1. **Pruebas Unitarias (`pytest`):**
   - Normalización de pronunciación de paraderos (`PD184` -> `P D 184`).
   - Normalización de consultas de esquinas para geocodificación.
   - Parseo de respuestas del planificador oficial de Red (itinerarios directos, transbordos bus-bus y bus-metro).
   - Formateo de frases de voz en todos los casos límite.
2. **Pruebas de Integración con Mocks:**
   - Simulación de `RouteToDestinationIntent` con Alexa Skills Kit SDK.
3. **Pruebas de Regresión:**
   - Verificar que los 41 tests existentes sigan pasando al 100%.
4. **Despliegue y Validación:**
   - Despliegue en Raspberry Pi 3 (`alexa-red.service`).
   - Publicación de modelos de interacción actualizados en Alexa Developer Console (`es-US`, `es-ES`, `es-MX`).
