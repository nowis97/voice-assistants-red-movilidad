# Destination Routing & Real-Time ETAs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable users to ask Alexa for transit directions to any destination (address, corner, landmark) in Greater Santiago, returning the exact bus lines, the stop code pronounced phonetically (`P D 184`), the real-time ETA (*«le faltan 4 minutos»*), and total travel time, supporting both direct routes and transfers.

**Architecture:** Integrate the official Red Movilidad multimodal route planner API (`https://appred.tstgo.cl/phone/v13/routeplanner/calculate`) with Nominatim geocoding in `location_service.py` and real-time arrival predictions via `api.xor.cl` in `red_service.py`. Handle user interaction via `RouteToDestinationIntent` in `alexa_handlers.py` and update multilingual Alexa interaction models.

**Tech Stack:** Python 3.11+, Alexa Skills Kit SDK (`ask-sdk-core`), SQLite (`stops.db`), Requests, Pytest, ASK CLI, systemd (Raspberry Pi 3).

**Spec:** `docs/superpowers/specs/2026-11-06-destination-routing-design.md`

## Global Constraints
- Preserve backward compatibility for all existing intents (`BusArrivalIntent`, `BipBalanceIntent`, `SaveStopIntent`, `SaveDirectionalStopIntent`, `SwitchDirectionIntent`).
- Stop code pronunciation MUST separate letters with spaces and keep digits together: `PD184` -> `P D 184` (*«P D ciento ochenta y cuatro»*).
- Never commit secrets (`.env`, `users.json`).
- Never touch port 3000 on the Raspberry Pi (reserved for Scrypted).
- Every task must carry its own failing test, minimal implementation, passing test, and git commit.

---

### Task 1: Destination Normalization and Spoken Stop Code Formatting

**Files:**
- Modify: `src/location_service.py`
- Test: `tests/test_location_service.py`

**Interfaces:**
- Produces:
  - `clean_spoken_stop_code(code: str) -> str`: Splits stop codes into spaced letters and integer number (e.g., `"PD184"` -> `"P D 184"`).
  - `normalize_destination_query(query: str) -> str`: Normalizes destination text for Nominatim, converting `"con"`, `"y"`, `"esq"` into `" / "` and appending `", Santiago, Chile"`.

- [ ] **Step 1: Write failing tests in `tests/test_location_service.py`**

```python
def test_clean_spoken_stop_code_standard():
    from src.location_service import clean_spoken_stop_code
    assert clean_spoken_stop_code("PD184") == "P D 184"
    assert clean_spoken_stop_code("PA345") == "P A 345"
    assert clean_spoken_stop_code("PC2") == "P C 2"


def test_clean_spoken_stop_code_edge_cases():
    from src.location_service import clean_spoken_stop_code
    assert clean_spoken_stop_code("") == ""
    assert clean_spoken_stop_code("METRO") == "METRO"


def test_normalize_destination_query():
    from src.location_service import normalize_destination_query
    q1 = normalize_destination_query("Pedro de Valdivia con Providencia")
    assert "Pedro de Valdivia / Providencia" in q1
    assert "Santiago, Chile" in q1

    q2 = normalize_destination_query("Grecia y Salvador")
    assert "Grecia / Salvador" in q2

    q3 = normalize_destination_query("Apoquindo 1234")
    assert "Apoquindo 1234" in q3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_location_service.py::test_clean_spoken_stop_code_standard -v`
Expected: FAIL with `ImportError: cannot import name 'clean_spoken_stop_code'`

- [ ] **Step 3: Implement minimal code in `src/location_service.py`**

```python
def clean_spoken_stop_code(code: str) -> str:
    """
    Formatea un código de paradero para que Alexa pronuncie las letras deletreadas
    y el número entero. Ej: 'PD184' -> 'P D 184' ('P D ciento ochenta y cuatro').
    """
    if not code:
        return ""
    clean = code.strip().upper()
    match = re.match(r"^([A-Z]+)(\d+)$", clean)
    if match:
        letters = " ".join(list(match.group(1)))
        number = match.group(2)
        return f"{letters} {number}"
    return clean


def normalize_destination_query(query: str, default_city: str = "Santiago", country: str = "Chile") -> str:
    """
    Normaliza el texto de destino dicho por el usuario para maximizar el acierto en OpenStreetMap Nominatim.
    Convierte 'con', 'y', 'esq' en ' / ' y agrega ciudad y país si no están presentes.
    """
    if not query:
        return ""
    q = query.strip()
    # Reemplazar intersecciones
    q = re.sub(r"\s+(?:con|y|esq\.?|esquina)\s+", " / ", q, flags=re.IGNORECASE)
    # Limpieza de espacios
    q = re.sub(r"\s+", " ", q).strip()
    # Agregar ciudad y país si no están
    if default_city.lower() not in q.lower():
        q = f"{q}, {default_city}"
    if country.lower() not in q.lower():
        q = f"{q}, {country}"
    return q
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_location_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/location_service.py tests/test_location_service.py
git commit -m "feat: add clean_spoken_stop_code and normalize_destination_query helpers"
```

---

### Task 2: Official Red Movilidad Route Planner Client

**Files:**
- Modify: `src/red_service.py`
- Test: `tests/test_red_service.py`

**Interfaces:**
- Consumes: `config.RED_HEADERS`, `TIMEOUT_SECONDS`
- Produces:
  - `plan_trip(origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float) -> Dict[str, Any]`:
    Queries `https://appred.tstgo.cl/phone/v13/routeplanner/calculate` and parses itineraries into structured direct routes and transfer options.

- [ ] **Step 1: Write failing test in `tests/test_red_service.py`**

```python
from unittest.mock import patch

def test_plan_trip_direct_route():
    from src.red_service import plan_trip
    mock_response = [
        {
            "duration": 1560,
            "transfers": 0,
            "legs": [
                {
                    "mode": "WALK",
                    "distance": 120.0,
                    "to": {"name": "PD184-Parada / Salvador", "stopId": "PD184"}
                },
                {
                    "mode": "BUS",
                    "route": "513",
                    "from": {"name": "PD184-Parada / Salvador", "stopId": "PD184"},
                    "to": {"name": "PC2-Parada 7 / (M) Pedro de Valdivia", "stopId": "PC2"},
                    "duration": 1200.0
                },
                {
                    "mode": "WALK",
                    "distance": 80.0,
                    "to": {"name": "Destination"}
                }
            ]
        }
    ]

    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_response

        res = plan_trip(-33.4578, -70.5891, -33.4225, -70.6094)
        assert res["success"] is True
        assert res["total_itineraries"] == 1
        assert len(res["direct_routes"]) == 1
        direct = res["direct_routes"][0]
        assert direct["route"] == "513"
        assert direct["from_stop_id"] == "PD184"
        assert direct["walk_distance_meters"] == 120
        assert direct["duration_minutes"] == 26


def test_plan_trip_transfer_route():
    from src.red_service import plan_trip
    mock_response = [
        {
            "duration": 2100,
            "transfers": 1,
            "legs": [
                {
                    "mode": "WALK",
                    "distance": 90.0,
                    "to": {"name": "PD184", "stopId": "PD184"}
                },
                {
                    "mode": "BUS",
                    "route": "506",
                    "from": {"name": "PD184", "stopId": "PD184"},
                    "to": {"name": "PC86-Plaza Italia", "stopId": "PC86"}
                },
                {
                    "mode": "WALK",
                    "distance": 50.0,
                    "to": {"name": "PA383", "stopId": "PA383"}
                },
                {
                    "mode": "BUS",
                    "route": "405",
                    "from": {"name": "PA383", "stopId": "PA383"},
                    "to": {"name": "PC153", "stopId": "PC153"}
                }
            ]
        }
    ]

    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_response

        res = plan_trip(-33.4578, -70.5891, -33.4000, -70.5500)
        assert res["success"] is True
        assert len(res["direct_routes"]) == 0
        assert len(res["transfer_routes"]) == 1
        transfer = res["transfer_routes"][0]
        assert transfer["first_route"] == "506"
        assert transfer["first_stop_id"] == "PD184"
        assert transfer["transfer_point"] == "Plaza Italia"
        assert transfer["second_route"] == "405"
        assert transfer["duration_minutes"] == 35
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_red_service.py::test_plan_trip_direct_route -v`
Expected: FAIL with `ImportError: cannot import name 'plan_trip'`

- [ ] **Step 3: Implement `plan_trip` in `src/red_service.py`**

```python
def plan_trip(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float
) -> Dict[str, Any]:
    """
    Consulta el planificador multimodal oficial de Red Movilidad para obtener rutas óptimas
    entre dos coordenadas de Santiago.
    """
    url = "https://appred.tstgo.cl/phone/v13/routeplanner/calculate"
    params = {
        "origin": f"{origin_lat},{origin_lon}",
        "destination": f"{dest_lat},{dest_lon}"
    }

    try:
        response = requests.get(url, headers=config.RED_HEADERS, params=params, timeout=TIMEOUT_SECONDS)
        if response.status_code != 200:
            logger.warning(f"Error del planificador Red Movilidad: HTTP {response.status_code}")
            return {
                "success": False,
                "error": f"Error del planificador de Red (HTTP {response.status_code}).",
                "direct_routes": [],
                "transfer_routes": [],
                "total_itineraries": 0
            }

        data = response.json()
        if not isinstance(data, list):
            return {
                "success": False,
                "error": "Respuesta inesperada del servicio de rutas.",
                "direct_routes": [],
                "transfer_routes": [],
                "total_itineraries": 0
            }

        direct_routes = []
        transfer_routes = []

        for itin in data:
            duration_min = round(itin.get("duration", 0) / 60)
            transfers = itin.get("transfers", 0)
            legs = itin.get("legs", [])

            transit_legs = [l for l in legs if l.get("mode") in ("BUS", "SUBWAY")]
            walk_legs = [l for l in legs if l.get("mode") == "WALK"]

            first_walk = walk_legs[0].get("distance", 0) if walk_legs else 0

            if transfers == 0 and transit_legs:
                t_leg = transit_legs[0]
                from_data = t_leg.get("from", {})
                to_data = t_leg.get("to", {})
                direct_routes.append({
                    "mode": t_leg.get("mode"),
                    "route": t_leg.get("route"),
                    "from_stop_id": from_data.get("stopId", ""),
                    "from_stop_name": clean_intersection_name(from_data.get("name", "")),
                    "to_stop_id": to_data.get("stopId", ""),
                    "to_stop_name": clean_intersection_name(to_data.get("name", "")),
                    "walk_distance_meters": int(first_walk),
                    "duration_minutes": duration_min
                })
            elif transfers >= 1 and len(transit_legs) >= 2:
                leg1 = transit_legs[0]
                leg2 = transit_legs[1]
                from1 = leg1.get("from", {})
                to1 = leg1.get("to", {})
                to2 = leg2.get("to", {})
                transfer_routes.append({
                    "first_mode": leg1.get("mode"),
                    "first_route": leg1.get("route"),
                    "first_stop_id": from1.get("stopId", ""),
                    "first_stop_name": clean_intersection_name(from1.get("name", "")),
                    "transfer_point": clean_intersection_name(to1.get("name", "")),
                    "second_mode": leg2.get("mode"),
                    "second_route": leg2.get("route"),
                    "destination_stop_name": clean_intersection_name(to2.get("name", "")),
                    "walk_distance_meters": int(first_walk),
                    "duration_minutes": duration_min,
                    "transfers": transfers
                })

        return {
            "success": True,
            "direct_routes": direct_routes,
            "transfer_routes": transfer_routes,
            "total_itineraries": len(data)
        }
    except requests.RequestException as e:
        logger.error(f"Fallo de conexión al planificador Red: {e}")
        return {
            "success": False,
            "error": "No fue posible conectar con el planificador de rutas de Red Movilidad.",
            "direct_routes": [],
            "transfer_routes": [],
            "total_itineraries": 0
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_red_service.py -k "test_plan_trip" -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/red_service.py tests/test_red_service.py
git commit -m "feat: implement official Red Movilidad route planner client"
```

---

### Task 3: Speech Formatting for Destination Routing and Real-Time ETAs

**Files:**
- Modify: `src/red_service.py`
- Test: `tests/test_red_service.py`

**Interfaces:**
- Consumes: `plan_trip`, `get_stop_predictions`, `clean_spoken_stop_code`
- Produces:
  - `format_route_speech(destination_text: str, origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float) -> str`

- [ ] **Step 1: Write failing tests in `tests/test_red_service.py`**

```python
def test_format_route_speech_direct_with_live_buses():
    from src.red_service import format_route_speech

    mock_plan = {
        "success": True,
        "direct_routes": [
            {
                "mode": "BUS",
                "route": "513",
                "from_stop_id": "PD184",
                "from_stop_name": "Avenida Grecia con Salvador",
                "walk_distance_meters": 120,
                "duration_minutes": 25
            }
        ],
        "transfer_routes": [],
        "total_itineraries": 1
    }

    mock_pred = {
        "success": True,
        "buses": [
            {"service": "513", "min_time": 4, "max_time": 4, "meters": 800}
        ]
    }

    with patch("src.red_service.plan_trip", return_value=mock_plan), \
         patch("src.red_service.get_stop_predictions", return_value=mock_pred):
        speech = format_route_speech("Pedro de Valdivia con Providencia", -33.4578, -70.5891, -33.4225, -70.6094)
        assert "513" in speech
        assert "P D 184" in speech
        assert "4 minutos" in speech
        assert "25 minutos" in speech


def test_format_route_speech_transfer():
    from src.red_service import format_route_speech

    mock_plan = {
        "success": True,
        "direct_routes": [],
        "transfer_routes": [
            {
                "first_mode": "BUS",
                "first_route": "506",
                "first_stop_id": "PD184",
                "first_stop_name": "Avenida Grecia con Salvador",
                "transfer_point": "Plaza Italia",
                "second_mode": "BUS",
                "second_route": "405",
                "duration_minutes": 38,
                "walk_distance_meters": 90
            }
        ],
        "total_itineraries": 1
    }

    mock_pred = {
        "success": True,
        "buses": [
            {"service": "506", "min_time": 5, "max_time": 5, "meters": 1200}
        ]
    }

    with patch("src.red_service.plan_trip", return_value=mock_plan), \
         patch("src.red_service.get_stop_predictions", return_value=mock_pred):
        speech = format_route_speech("Vitacura", -33.4578, -70.5891, -33.4000, -70.5500)
        assert "no hay micro directa" in speech
        assert "506" in speech
        assert "P D 184" in speech
        assert "Plaza Italia" in speech
        assert "405" in speech
        assert "38 minutos" in speech


def test_format_route_speech_walking_distance():
    from src.red_service import format_route_speech
    # Distancia menor a 150m entre origen y destino
    speech = format_route_speech("La esquina de al lado", -33.4578, -70.5891, -33.4579, -70.5892)
    assert "caminando" in speech
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_red_service.py -k "test_format_route_speech" -v`
Expected: FAIL with `ImportError: cannot import name 'format_route_speech'`

- [ ] **Step 3: Implement `format_route_speech` in `src/red_service.py`**

```python
import math
from src.location_service import clean_spoken_stop_code

def format_route_speech(
    destination_text: str,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float
) -> str:
    """
    Construye la respuesta hablada óptima de Alexa indicando la micro a tomar,
    el paradero con fonética clara ('P D 184'), el tiempo en vivo y la duración.
    """
    # 1. Verificar si está a distancia caminable (< 200m)
    dlat = math.radians(dest_lat - origin_lat)
    dlon = math.radians(dest_lon - origin_lon)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(origin_lat)) * math.cos(math.radians(dest_lat)) *
         math.sin(dlon / 2) ** 2)
    dist_meters = int(6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

    if dist_meters < 200:
        return "Ese destino está a solo una o dos cuadras de donde te encuentras, puedes llegar caminando en unos minutos."

    # 2. Consultar el planificador de Red
    plan = plan_trip(origin_lat, origin_lon, dest_lat, dest_lon)
    if not plan["success"]:
        return plan.get("error", "No pude consultar la ruta en este momento.")

    directs = plan["direct_routes"]
    transfers = plan["transfer_routes"]

    if not directs and not transfers:
        return f"No encontré recorridos disponibles para ir a {destination_text} en este momento."

    # Caso 1: Ruta Directa
    if directs:
        best_direct = directs[0]
        route = best_direct["route"]
        stop_id = best_direct["from_stop_id"]
        spoken_stop = clean_spoken_stop_code(stop_id)
        duration = best_direct["duration_minutes"]
        walk_m = best_direct.get("walk_distance_meters", 0)

        # Consultar predictivo en tiempo real para esa micro en ese paradero
        pred = get_stop_predictions(stop_id, route)
        eta_phrase = ""
        if pred["success"] and pred["buses"]:
            first_bus = pred["buses"][0]
            eta_phrase = f" La micro {_format_single_bus_arrival(first_bus)}."
        else:
            eta_phrase = " No hay buses en camino reportados en este momento."

        walk_phrase = f", a {walk_m} metros," if walk_m > 30 else ""
        return (
            f"Para ir a {destination_text}, te sirve la {route} en tu paradero {spoken_stop}{walk_phrase}. "
            f"{eta_phrase.strip()} El viaje toma unos {duration} minutos."
        )

    # Caso 2: Ruta con Transbordo
    best_tr = transfers[0]
    r1 = best_tr["first_route"]
    s1 = clean_spoken_stop_code(best_tr["first_stop_id"])
    tr_point = best_tr["transfer_point"]
    r2 = best_tr["second_route"]
    dur = best_tr["duration_minutes"]

    pred1 = get_stop_predictions(best_tr["first_stop_id"], r1)
    eta1 = ""
    if pred1["success"] and pred1["buses"]:
        eta1 = f" que {_format_single_bus_arrival(pred1['buses'][0])},"

    return (
        f"Para llegar a {destination_text} no hay micro directa desde tu esquina. "
        f"Te sugiero tomar la {r1} en el paradero {s1}{eta1} bajarte en {tr_point} y "
        f"combinar con la {r2}. En total son unos {dur} minutos de viaje."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_red_service.py -k "test_format_route_speech" -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/red_service.py tests/test_red_service.py
git commit -m "feat: add format_route_speech for destination routing"
```

---

### Task 4: Alexa Handler `RouteToDestinationIntentHandler` and Interaction Models

**Files:**
- Modify: `src/alexa_handlers.py`
- Modify: `lambda_function.py`
- Modify: `skill-package/interactionModels/custom/es-US.json`
- Modify: `skill-package/interactionModels/custom/es-ES.json`
- Modify: `skill-package/interactionModels/custom/es-MX.json`
- Test: `tests/test_handlers.py`

**Interfaces:**
- Handles: `RouteToDestinationIntent` with slots `Destination` and optional `Origin`.
- Uses: `geocode_address`, `normalize_destination_query`, `format_route_speech`, `config.get_user_stops`, `get_coordinates_from_request`.

- [ ] **Step 1: Write failing test in `tests/test_handlers.py`**

```python
def test_route_to_destination_intent_handler():
    from src.alexa_handlers import RouteToDestinationIntentHandler
    from ask_sdk_core.handler_input import HandlerInput
    from ask_sdk_model import RequestEnvelope, Request, IntentRequest, Intent, Slot

    req = IntentRequest(
        intent=Intent(
            name="RouteToDestinationIntent",
            slots={
                "Destination": Slot(name="Destination", value="Metro Tobalaba")
            }
        )
    )
    envelope = RequestEnvelope(request=req)
    handler_input = HandlerInput(request_envelope=envelope)

    handler = RouteToDestinationIntentHandler()
    assert handler.can_handle(handler_input) is True

    with patch("src.alexa_handlers.geocode_address", return_value=(-33.4179, -70.6016)), \
         patch("src.alexa_handlers.format_route_speech", return_value="Para ir a Metro Tobalaba te sirve la 513."):
        resp = handler.handle(handler_input)
        assert "513" in resp.output_speech.ssml
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_handlers.py -k "test_route_to_destination" -v`
Expected: FAIL with `ImportError: cannot import name 'RouteToDestinationIntentHandler'`

- [ ] **Step 3: Implement `RouteToDestinationIntentHandler` in `src/alexa_handlers.py` and register in `lambda_function.py`**

```python
class RouteToDestinationIntentHandler(AbstractRequestHandler):
    """Maneja la consulta de cómo llegar a un destino o qué micros sirven."""
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("RouteToDestinationIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        slots = handler_input.request_envelope.request.intent.slots or {}
        dest_slot = slots.get("Destination")
        dest_value = dest_slot.value if dest_slot else None

        if not dest_value or not dest_value.strip():
            speech = "Por favor dime a qué dirección, esquina o lugar quieres ir."
            return (
                handler_input.response_builder
                .speak(speech)
                .ask("¿A dónde deseas ir?")
                .response
            )

        # 1. Resolver destino a coordenadas
        norm_dest = normalize_destination_query(dest_value)
        dest_coords = geocode_address(norm_dest)
        if not dest_coords:
            # Reintentar sin normalización adicional por si es un hito directo
            dest_coords = geocode_address(dest_value)

        if not dest_coords:
            speech = (
                f"No pude encontrar la dirección o esquina {dest_value}. "
                "Por favor intenta diciendo la calle principal y una intersección, por ejemplo: Providencia con Pedro de Valdivia."
            )
            return handler_input.response_builder.speak(speech).response

        dest_lat, dest_lon = dest_coords

        # 2. Resolver origen (explícito o automático)
        orig_slot = slots.get("Origin")
        orig_value = orig_slot.value if orig_slot else None
        orig_coords = None

        if orig_value:
            norm_orig = normalize_destination_query(orig_value)
            orig_coords = geocode_address(norm_orig) or geocode_address(orig_value)

        if not orig_coords:
            # Obtener desde GPS / Device Address o paradero guardado
            coords_info = get_coordinates_from_request(handler_input)
            if coords_info:
                orig_coords = (coords_info[0], coords_info[1])
            else:
                user_id = handler_input.request_envelope.context.system.user.user_id
                user_stops = config.get_user_stops(user_id)
                stop_code = user_stops.get("ida") or user_stops.get("vuelta") or config.DEFAULT_STOP_CODE
                # Buscar lat/lon del paradero en stops.db
                conn = sqlite3.connect(location_service.DB_PATH)
                c = conn.cursor()
                c.execute("SELECT lat, lon FROM stops WHERE code = ?", (stop_code,))
                row = c.fetchone()
                conn.close()
                if row:
                    orig_coords = (row[0], row[1])
                else:
                    orig_coords = (-33.4578, -70.5891) # Fallback centro/origen

        # 3. Construir respuesta hablada
        speech = format_route_speech(dest_value, orig_coords[0], orig_coords[1], dest_lat, dest_lon)
        return handler_input.response_builder.speak(speech).response
```

- [ ] **Step 4: Update interaction models (`es-US.json`, `es-ES.json`, `es-MX.json`)**

Add intent:
```json
{
  "name": "RouteToDestinationIntent",
  "slots": [
    {
      "name": "Destination",
      "type": "AMAZON.SearchQuery"
    },
    {
      "name": "Origin",
      "type": "AMAZON.SearchQuery"
    }
  ],
  "samples": [
    "qué micros me sirven para ir a {Destination}",
    "qué micro me sirve para ir a {Destination}",
    "cómo llego a {Destination}",
    "cómo me voy a {Destination}",
    "qué micro tomo para {Destination}",
    "qué micro tomo para ir a {Destination}",
    "dime cómo llegar a {Destination}",
    "dime qué micro me sirve a {Destination}",
    "cuál micro me sirve para ir a {Destination}",
    "cómo llego desde {Origin} hasta {Destination}",
    "qué micro me sirve desde {Origin} hasta {Destination}"
  ]
}
```

- [ ] **Step 5: Run tests to verify all pass**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit changes**

```bash
git add src/alexa_handlers.py lambda_function.py skill-package/ tests/test_handlers.py
git commit -m "feat: add RouteToDestinationIntentHandler and update interaction models"
```

---

### Task 5: End-to-End Verification, Deployment to Raspberry Pi, and ASK CLI Sync

**Files:**
- None (Deployment & Verification)

- [ ] **Step 1: Run full test suite with coverage**

Run: `python -m pytest --cov=src tests/`
Expected: 100% tests passing, clean assertions.

- [ ] **Step 2: Deploy to Raspberry Pi 3**

Run rsync or scp to `nowis@192.168.0.112:/home/nowis/alexa-red-movilidad/`, restart `alexa-red.service`, and verify `systemctl status alexa-red`.

- [ ] **Step 3: Push to GitHub repository**

Run: `git push origin master`
Expected: Triggers GitHub Actions workflow (`deploy-skill.yml`) to deploy new interaction models to Alexa Developer Console.

- [ ] **Step 4: Verify Alexa SMAPI Build Status**

Run: `ask smapi get-skill-status --skill-id amzn1.ask.skill.2aa8d315-fc92-49e2-99e1-63943a4d2aef`
Expected: `interactionModel.es-US.lastUpdateTimeStatus == "SUCCEEDED"`.
