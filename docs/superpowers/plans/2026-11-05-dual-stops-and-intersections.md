# Paraderos Dobles, Intersecciones Naturales y Publicación GitHub - Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar soporte para paraderos dobles enfrentados (ida y vuelta), reconocimiento y habla de intersecciones naturales de calles en Santiago de Chile, renombrar la Skill a "Red Movilidad" y publicar el proyecto en GitHub como repositorio público `voice-assistants-red-movilidad`.

**Architecture:** Módulo de geolocalización e intersecciones en SQLite (`location_service.py`), persistencia de esquinas y sentidos en `config.py`, constructores de lenguaje natural para predicciones duales en `red_service.py`, intents y modelos Alexa enriquecidos (`alexa_handlers.py`), y despliegue continuo a Raspberry Pi y GitHub.

**Tech Stack:** Python 3.11+, FastAPI, ASK SDK v2 (Alexa Skills Kit), SQLite3, Requests, Pytest, Uvicorn, GitHub CLI (`gh`).

**Spec:** `docs/superpowers/specs/2026-11-05-dual-stops-and-intersections-design.md`

## Global Constraints
- Repositorio público exacto: `voice-assistants-red-movilidad`.
- Nombre de Skill e Invocación exactos: Invocación `red movilidad`, Manifest `Red Movilidad`.
- Privacidad y Secretos: `.env` y `users.json` NUNCA deben commitearse ni subirse a GitHub.
- Seguridad en Raspberry Pi: Respetar el puerto 3000 de Scrypted (cámaras de seguridad), usar exclusivamente el puerto 8000 para `alexa-red.service`.
- Retrocompatibilidad: Si un usuario solo tiene un paradero configurado, debe funcionar sin errores como fallback para ambos sentidos.

---

### Task 1: Limpiador de Intersecciones y Búsqueda de Paraderos Opuestos

**Files:**
- Create: `tests/test_location_service.py`
- Modify: `src/location_service.py`

**Interfaces:**
- Consumes: `stops.db` SQLite schema (`code TEXT PRIMARY KEY, name TEXT, lat REAL, lon REAL`).
- Produces:
  - `clean_intersection_name(raw_name: str) -> str`: Normaliza nombres crudos GTFS a nombres hablados naturales en español.
  - `find_opposing_stop(stop_code: str) -> Optional[Dict[str, Any]]`: Encuentra el paradero en la vereda contraria por proximidad geográfica (<180m) y correspondencia de eje vial.
  - `find_stops_by_intersection(street1: str, street2: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]`: Busca paraderos en una esquina y retorna la tupla `(stop_ida, stop_vuelta)`.

- [ ] **Step 1: Escribir los tests unitarios fallidos en `tests/test_location_service.py`**

```python
import pytest
from src.location_service import (
    clean_intersection_name,
    find_opposing_stop,
    find_stops_by_intersection,
)


def test_clean_intersection_name_standard():
    raw = "PC186-Avenida Apoquindo / Esq. El Bosque Norte"
    cleaned = clean_intersection_name(raw)
    assert cleaned == "Avenida Apoquindo con El Bosque Norte"


def test_clean_intersection_name_abbreviations():
    raw = "PD184-Av. Grecia / Esq. Salvador"
    cleaned = clean_intersection_name(raw)
    assert cleaned == "Avenida Grecia con Salvador"


def test_clean_intersection_name_metro():
    raw = "PA345-Parada 4 / (M) Universidad De Chile"
    cleaned = clean_intersection_name(raw)
    assert "Metro Universidad De Chile" in cleaned
    assert "PA345" not in cleaned


def test_find_opposing_stop_pc186():
    # PC186 (Apoquindo / El Bosque Norte) tiene a PC156 enfrente en Av. Apoquindo
    opposing = find_opposing_stop("PC186")
    assert opposing is not None
    assert opposing["code"] == "PC156"
    assert "Apoquindo" in opposing["name"]
    assert opposing["distance_meters"] < 250


def test_find_stops_by_intersection_apoquindo_bosque():
    ida, vuelta = find_stops_by_intersection("Apoquindo", "Bosque")
    assert ida is not None
    assert ida["code"] == "PC186"
    assert vuelta is not None
    assert vuelta["code"] == "PC156"


def test_find_stops_by_intersection_not_found():
    ida, vuelta = find_stops_by_intersection("CalleFalsaInexistente999", "OtraCalle")
    assert ida is None
    assert vuelta is None
```

- [ ] **Step 2: Ejecutar test para verificar que falla**

Ejecutar:
```powershell
python -m pytest tests/test_location_service.py -v
```
Resultado esperado: FAIL con `ImportError: cannot import name 'clean_intersection_name' from 'src.location_service'`.

- [ ] **Step 3: Implementar funciones en `src/location_service.py`**

Agregar las siguientes funciones a `src/location_service.py`:

```python
import re

def clean_intersection_name(raw_name: str) -> str:
    """
    Transforma un nombre técnico GTFS de paradero en una frase hablada natural.
    Ejemplos:
      'PC186-Avenida Apoquindo / Esq. El Bosque Norte' -> 'Avenida Apoquindo con El Bosque Norte'
      'PD184-Av. Grecia / Esq. Salvador' -> 'Avenida Grecia con Salvador'
      'PA345-Parada 4 / (M) Universidad De Chile' -> 'Parada 4 con Metro Universidad De Chile'
    """
    if not raw_name:
        return ""

    # 1. Eliminar prefijo de código (ej: 'PC186-', 'PA345 - ')
    s = re.sub(r"^[A-Z0-9]+[-\s]+", "", raw_name.strip())

    # 2. Expandir indicador de Metro
    s = re.sub(r"\(M\)", "Metro", s)

    # 3. Expandir abreviaturas comunes de vías
    s = re.sub(r"\bAv\.\s*", "Avenida ", s, flags=re.IGNORECASE)
    s = re.sub(r"\bPque\.\s*", "Parque ", s, flags=re.IGNORECASE)
    s = re.sub(r"\bPje\.\s*", "Pasaje ", s, flags=re.IGNORECASE)

    # 4. Normalizar intersección (/ Esq. o / por 'con')
    s = re.sub(r"/\s*(?:Esq\.?|esq\.?)?\s*", " con ", s)

    # 5. Limpieza de espacios redundantes
    s = re.sub(r"\s+", " ", s).strip()
    return s


def find_opposing_stop(stop_code: str, max_meters: int = 250) -> Optional[Dict[str, Any]]:
    """
    Encuentra el paradero enfrentado en la vereda contraria para un código dado,
    buscando en stops.db por proximidad geográfica (<250m) en el mismo eje vial.
    """
    if not os.path.exists(DB_PATH) or not stop_code:
        return None

    clean_code = stop_code.strip().upper()
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Obtener datos del paradero origen
        c.execute("SELECT code, name, lat, lon FROM stops WHERE code = ?", (clean_code,))
        origin = c.fetchone()
        if not origin:
            conn.close()
            return None

        _, origin_name, o_lat, o_lon = origin

        # Extraer eje principal (antes de 'con' o '/')
        cleaned_origin = clean_intersection_name(origin_name)
        main_axis = cleaned_origin.split(" con ")[0].strip() if " con " in cleaned_origin else cleaned_origin

        # Buscar paraderos cercanos dentro de un radio de ~250m (~0.0025 grados)
        c.execute("""
            SELECT code, name, lat, lon
            FROM stops
            WHERE code != ?
              AND lat BETWEEN ? AND ?
              AND lon BETWEEN ? AND ?
        """, (clean_code, o_lat - 0.0025, o_lat + 0.0025, o_lon - 0.0025, o_lon + 0.0025))

        candidates = c.fetchall()
        conn.close()

        best_stop = None
        min_dist = float("inf")

        for c_code, c_name, c_lat, c_lon in candidates:
            # Calcular distancia Haversine
            dlat = math.radians(c_lat - o_lat)
            dlon = math.radians(c_lon - o_lon)
            a = (math.sin(dlat / 2) ** 2 +
                 math.cos(math.radians(o_lat)) * math.cos(math.radians(c_lat)) *
                 math.sin(dlon / 2) ** 2)
            dist_m = int(6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

            if dist_m > max_meters:
                continue

            cleaned_cand = clean_intersection_name(c_name)
            # Priorizar paraderos que compartan el mismo eje vial
            axis_match = (main_axis.lower() in cleaned_cand.lower() or
                          ("metro" in cleaned_origin.lower() and "metro" in cleaned_cand.lower()))

            if axis_match and dist_m < min_dist:
                min_dist = dist_m
                best_stop = {
                    "code": c_code,
                    "name": cleaned_cand,
                    "latitude": c_lat,
                    "longitude": c_lon,
                    "distance_meters": dist_m
                }

        return best_stop
    except Exception as e:
        logger.error(f"Error buscando paradero opuesto a {stop_code}: {e}", exc_info=True)
        return None


def find_stops_by_intersection(street1: str, street2: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Busca los dos paraderos enfrentados en una esquina dada por dos calles.
    Retorna (stop_ida, stop_vuelta).
    """
    if not os.path.exists(DB_PATH) or not street1:
        return None, None

    s1 = street1.strip()
    s2 = street2.strip() if street2 else ""

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        query = "SELECT code, name, lat, lon FROM stops WHERE name LIKE ?"
        params = [f"%{s1}%"]
        if s2:
            query += " AND name LIKE ?"
            params.append(f"%{s2}%")

        c.execute(query, tuple(params))
        rows = c.fetchall()
        conn.close()

        if not rows:
            return None, None

        # Paradero principal de referencia
        p1_code, p1_name, p1_lat, p1_lon = rows[0]
        stop_ida = {
            "code": p1_code,
            "name": clean_intersection_name(p1_name),
            "latitude": p1_lat,
            "longitude": p1_lon,
            "distance_meters": 0
        }

        # Si encontramos dos directamente en la consulta
        if len(rows) >= 2:
            p2_code, p2_name, p2_lat, p2_lon = rows[1]
            stop_vuelta = {
                "code": p2_code,
                "name": clean_intersection_name(p2_name),
                "latitude": p2_lat,
                "longitude": p2_lon,
                "distance_meters": 0
            }
            return stop_ida, stop_vuelta

        # Si solo encontramos uno con ambos nombres, buscar su opuesto en la vereda del frente
        opposing = find_opposing_stop(p1_code)
        return stop_ida, opposing
    except Exception as e:
        logger.error(f"Error buscando paraderos por esquina {street1} con {street2}: {e}", exc_info=True)
        return None, None
```

- [ ] **Step 4: Ejecutar tests para verificar que pasan**

Ejecutar:
```powershell
python -m pytest tests/test_location_service.py -v
```
Resultado esperado: `6 passed`.

- [ ] **Step 5: Commit de Task 1**

```bash
git add tests/test_location_service.py src/location_service.py
git commit -m "feat(location): add intersection cleaning and opposing stop resolution"
```

---

### Task 2: Almacenamiento y Configuración de Paraderos Dobles

**Files:**
- Create: `tests/test_config.py`
- Modify: `config.py`

**Interfaces:**
- Consumes: `users.json`, `clean_alphanumeric_code`.
- Produces:
  - `get_user_stops(user_key_or_name: Optional[str] = None, person_id: Optional[str] = None) -> Dict[str, Any]`: Retorna un diccionario con `{ "ida": { "code": ..., "name": ... }, "vuelta": { "code": ..., "name": ... }, "intersection": ... }`.
  - `save_stops_pair(target_key: str, stop_ida: Dict[str, Any], stop_vuelta: Optional[Dict[str, Any]] = None, intersection: Optional[str] = None) -> Tuple[bool, str, Dict[str, Any]]`: Guarda la tupla de paraderos en el perfil de usuario.

- [ ] **Step 1: Escribir los tests unitarios fallidos en `tests/test_config.py`**

```python
import os
import json
import pytest
import config


def test_get_user_stops_fallback_default(monkeypatch, tmp_path):
    test_users_file = str(tmp_path / "users.json")
    monkeypatch.setattr(config, "USERS_FILE", test_users_file)

    users = {
        "user1": {
            "name": "Simón",
            "aliases": ["simon"],
            "card": "12345678",
            "stop": "PA345",
            "service": "513",
            "person_id": ""
        }
    }
    with open(test_users_file, "w", encoding="utf-8") as f:
        json.dump(users, f)

    stops_info = config.get_user_stops("user1")
    assert stops_info["ida"]["code"] == "PA345"
    assert stops_info["vuelta"]["code"] == "PA345"


def test_save_stops_pair_updates_user(monkeypatch, tmp_path):
    test_users_file = str(tmp_path / "users.json")
    monkeypatch.setattr(config, "USERS_FILE", test_users_file)

    users = {
        "user1": {
            "name": "Simón",
            "aliases": ["simon"],
            "card": "12345678",
            "stop": "PA345",
            "service": "513",
            "person_id": ""
        }
    }
    with open(test_users_file, "w", encoding="utf-8") as f:
        json.dump(users, f)

    stop_ida = {"code": "PC186", "name": "Avenida Apoquindo con El Bosque Norte"}
    stop_vuelta = {"code": "PC156", "name": "Avenida Apoquindo con El Bosque Sur"}

    success, msg, user = config.save_stops_pair(
        target_key="user1",
        stop_ida=stop_ida,
        stop_vuelta=stop_vuelta,
        intersection="Avenida Apoquindo con El Bosque"
    )

    assert success is True
    assert "PC186" in msg and "PC156" in msg
    assert user["stops"]["ida"]["code"] == "PC186"
    assert user["stops"]["vuelta"]["code"] == "PC156"
    assert user["stops"]["intersection"] == "Avenida Apoquindo con El Bosque"
```

- [ ] **Step 2: Ejecutar test para verificar que falla**

Ejecutar:
```powershell
python -m pytest tests/test_config.py -v
```
Resultado esperado: FAIL con `AttributeError: module 'config' has no attribute 'get_user_stops'`.

- [ ] **Step 3: Implementar funciones en `config.py`**

Agregar a `config.py`:

```python
def get_user_stops(
    name_query: Optional[str] = None,
    person_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Retorna la configuración de paraderos de ida y vuelta para el usuario resuelto.
    Mantiene compatibilidad con esquemas antiguos que solo tienen 'stop'.
    """
    user = resolve_user(name_query=name_query, person_id=person_id)

    if "stops" in user and isinstance(user["stops"], dict):
        ida_data = user["stops"].get("ida", {})
        vuelta_data = user["stops"].get("vuelta", {})
        intersection = user["stops"].get("intersection", "")

        return {
            "ida": {
                "code": ida_data.get("code") or user.get("stop", DEFAULT_STOP_CODE),
                "name": ida_data.get("name", "paradero de ida"),
                "direction": ida_data.get("direction", "de ida")
            },
            "vuelta": {
                "code": vuelta_data.get("code") or user.get("stop", DEFAULT_STOP_CODE),
                "name": vuelta_data.get("name", "paradero de vuelta"),
                "direction": vuelta_data.get("direction", "de regreso")
            },
            "intersection": intersection
        }

    # Fallback para perfil tradicional de 1 solo paradero
    default_code = user.get("stop", DEFAULT_STOP_CODE)
    return {
        "ida": {"code": default_code, "name": "paradero habitual", "direction": "de ida"},
        "vuelta": {"code": default_code, "name": "paradero habitual", "direction": "de regreso"},
        "intersection": ""
    }


def save_stops_pair(
    target_key: str,
    stop_ida: Dict[str, Any],
    stop_vuelta: Optional[Dict[str, Any]] = None,
    intersection: Optional[str] = None
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Guarda el par de paraderos (ida y vuelta) asociados a la esquina del usuario.
    """
    users = load_users()
    if target_key not in users:
        target_key = "user1"

    target_user = users[target_key]

    ida_code = clean_alphanumeric_code(stop_ida.get("code", ""))
    ida_name = stop_ida.get("name", "")

    vuelta_code = clean_alphanumeric_code(stop_vuelta.get("code", "")) if stop_vuelta else ida_code
    vuelta_name = stop_vuelta.get("name", "") if stop_vuelta else ida_name

    target_user["stops"] = {
        "ida": {"code": ida_code, "name": ida_name, "direction": "de ida"},
        "vuelta": {"code": vuelta_code, "name": vuelta_name, "direction": "de vuelta"},
        "intersection": intersection or ida_name
    }
    # Mantener sincronizado el fallback legacy
    target_user["stop"] = ida_code

    save_users(users)
    global USERS_BIP
    USERS_BIP = users

    user_name = target_user.get("name", "Usuario")
    if ida_code != vuelta_code:
        msg = f"Guardé tu esquina {intersection or ida_name} para {user_name}: paradero de ida {ida_code} y de vuelta {vuelta_code}."
    else:
        msg = f"Guardé el paradero {ida_code} para {user_name}."

    return True, msg, target_user
```

- [ ] **Step 4: Ejecutar tests para verificar que pasan**

Ejecutar:
```powershell
python -m pytest tests/test_config.py -v
```
Resultado esperado: `2 passed`.

- [ ] **Step 5: Commit de Task 2**

```bash
git add tests/test_config.py config.py
git commit -m "feat(config): add dual stops storage and resolution"
```

---

### Task 3: Formateo de Habla para Consulta Dual e Intersecciones

**Files:**
- Modify: `src/red_service.py`
- Modify: `tests/test_red_service.py`

**Interfaces:**
- Consumes: `get_stop_predictions`, `clean_intersection_name`.
- Produces:
  - `format_dual_prediction_speech(linea: str, stop_ida: Dict[str, Any], stop_vuelta: Optional[Dict[str, Any]], intersection: Optional[str] = None, sentido_query: Optional[str] = None) -> str`: Construye la frase de Alexa detallando los tiempos en ambas veredas o en un sentido exclusivo.
  - Actualización de `format_travel_summary_speech` para admitir paraderos duales.

- [ ] **Step 1: Escribir tests para `format_dual_prediction_speech` en `tests/test_red_service.py`**

Agregar a `tests/test_red_service.py`:

```python
from unittest.mock import patch
from src import red_service


@patch("src.red_service.get_stop_predictions")
def test_format_dual_prediction_both_directions(mock_preds):
    def side_effect(stop_code, service):
        if stop_code == "PD184":
            return {
                "success": True,
                "stop_code": "PD184",
                "stop_name": "Av. Grecia / Esq. Salvador",
                "target_service": "513",
                "buses": [{"service": "513", "meters": 1200, "min_time": 4, "max_time": 6}],
                "raw_services_count": 1
            }
        else:
            return {
                "success": True,
                "stop_code": "PD200",
                "stop_name": "Av. Grecia / Esq. Salvador",
                "target_service": "513",
                "buses": [{"service": "513", "meters": 2500, "min_time": 10, "max_time": 12}],
                "raw_services_count": 1
            }

    mock_preds.side_effect = side_effect

    speech = red_service.format_dual_prediction_speech(
        linea="513",
        stop_ida={"code": "PD184", "name": "Avenida Grecia con Salvador"},
        stop_vuelta={"code": "PD200", "name": "Avenida Grecia con Salvador"},
        intersection="Avenida Grecia con Salvador"
    )

    assert "Para la 513 en Avenida Grecia con Salvador" in speech
    assert "paradero PD184" in speech
    assert "vereda del frente (paradero PD200)" in speech
    assert "6 minutos" in speech


@patch("src.red_service.get_stop_predictions")
def test_format_dual_prediction_specific_direction(mock_preds):
    mock_preds.return_value = {
        "success": True,
        "stop_code": "PD184",
        "stop_name": "Av. Grecia / Esq. Salvador",
        "target_service": "513",
        "buses": [{"service": "513", "meters": 800, "min_time": 3, "max_time": 4}],
        "raw_services_count": 1
    }

    speech = red_service.format_dual_prediction_speech(
        linea="513",
        stop_ida={"code": "PD184", "name": "Avenida Grecia con Salvador"},
        stop_vuelta={"code": "PD200", "name": "Avenida Grecia con Salvador"},
        intersection="Avenida Grecia con Salvador",
        sentido_query="ida"
    )

    assert "La 513 de ida viene en Avenida Grecia con Salvador" in speech
    assert "PD184" in speech
    assert "PD200" not in speech
```

- [ ] **Step 2: Ejecutar test para verificar que falla**

Ejecutar:
```powershell
python -m pytest tests/test_red_service.py -k test_format_dual_prediction -v
```
Resultado esperado: FAIL con `AttributeError: module 'src.red_service' has no attribute 'format_dual_prediction_speech'`.

- [ ] **Step 3: Implementar `format_dual_prediction_speech` en `src/red_service.py`**

Agregar en `src/red_service.py`:

```python
def _format_single_bus_arrival(bus: Dict[str, Any]) -> str:
    """Helper interno para describir llegada de un bus."""
    max_t = bus.get("max_time", 0)
    min_t = bus.get("min_time", 0)
    meters = bus.get("meters", 0)

    if max_t <= 1 or meters <= 100:
        return "está llegando ahora mismo"
    elif min_t == max_t or min_t == 0:
        return f"le faltan unos {max_t} minutos"
    else:
        return f"le faltan entre {min_t} y {max_t} minutos"


def format_dual_prediction_speech(
    linea: str,
    stop_ida: Dict[str, Any],
    stop_vuelta: Optional[Dict[str, Any]] = None,
    intersection: Optional[str] = None,
    sentido_query: Optional[str] = None
) -> str:
    """
    Construye la respuesta hablada de predicción para un recorrido en la esquina del usuario,
    reportando ambos paraderos enfrentados o discriminando si el usuario pidió un sentido específico.
    """
    code_ida = stop_ida.get("code")
    code_vuelta = stop_vuelta.get("code") if stop_vuelta else None
    corner = intersection or stop_ida.get("name", "tu esquina")

    # Si el usuario consultó un sentido específico (ej: "de ida", "hacia el centro", "vuelta", "regreso")
    if sentido_query:
        norm_sentido = sentido_query.lower()
        es_vuelta = any(w in norm_sentido for w in ["vuelta", "regreso", "casa", "peñalolén", "barrio"])
        target_stop = stop_vuelta if (es_vuelta and stop_vuelta) else stop_ida
        label_sentido = "de vuelta" if (es_vuelta and stop_vuelta) else "de ida"

        res = get_stop_predictions(target_stop.get("code"), linea)
        if not res["success"]:
            return f"No pude consultar la {linea} {label_sentido} en el paradero {target_stop.get('code')}."

        buses = res.get("buses", [])
        if not buses:
            return f"No vienen micros de la {linea} {label_sentido} acercándose al paradero {target_stop.get('code')} en {corner}."

        first = buses[0]
        arrival_str = _format_single_bus_arrival(first)
        dist_str = f"a {first['meters']} metros" if first.get("meters") else "en camino"
        return f"La {linea} {label_sentido} viene en {corner} (paradero {target_stop.get('code')}) {dist_str}, {arrival_str}."

    # Consulta general sin sentido especificado: consultar ambos paraderos
    res_ida = get_stop_predictions(code_ida, linea)
    res_vuelta = get_stop_predictions(code_vuelta, linea) if (code_vuelta and code_vuelta != code_ida) else None

    buses_ida = res_ida.get("buses", []) if res_ida.get("success") else []
    buses_vuelta = res_vuelta.get("buses", []) if (res_vuelta and res_vuelta.get("success")) else []

    if not buses_ida and not buses_vuelta:
        return f"No hay buses del recorrido {linea} aproximándose a tu esquina {corner} en este momento."

    parts = [f"Para la {linea} en {corner}:"]

    if buses_ida:
        first_ida = buses_ida[0]
        arr_ida = _format_single_bus_arrival(first_ida)
        parts.append(f"de ida en el paradero {code_ida} {arr_ida};")
    else:
        parts.append(f"de ida en el paradero {code_ida} no vienen buses;")

    if code_vuelta and code_vuelta != code_ida:
        if buses_vuelta:
            first_v = buses_vuelta[0]
            arr_v = _format_single_bus_arrival(first_v)
            parts.append(f"y en la vereda del frente (paradero {code_vuelta}) {arr_v}.")
        else:
            parts.append(f"y en la vereda del frente (paradero {code_vuelta}) no vienen buses próximos.")
    elif not buses_ida:
        return f"No veo micros de la {linea} en camino al paradero {code_ida}."

    return " ".join(parts)
```

- [ ] **Step 4: Ejecutar tests para verificar que pasan**

Ejecutar:
```powershell
python -m pytest tests/test_red_service.py -v
```
Resultado esperado: `12 passed`.

- [ ] **Step 5: Commit de Task 3**

```bash
git add src/red_service.py tests/test_red_service.py
git commit -m "feat(speech): support dual predictions and spoken intersections"
```

---

### Task 4: Voice Handlers y Modelos de Interacción de Alexa

**Files:**
- Modify: `src/alexa_handlers.py`
- Modify: `skill-package/interactionModels/custom/es-ES.json`
- Modify: `skill-package/interactionModels/custom/es-US.json`
- Modify: `skill-package/interactionModels/custom/es-MX.json`
- Modify: `skill-package/skill.json`
- Modify: `tests/test_handlers.py`

**Interfaces:**
- Consumes: `format_dual_prediction_speech`, `find_stops_by_intersection`, `find_opposing_stop`, `get_user_stops`, `save_stops_pair`.
- Produces:
  - Actualización de `PrediccionMicroIntentHandler` para aceptar slots de `sentido` y consultar paraderos dobles.
  - Actualización de `GuardarPreferenciaIntentHandler` para registrar esquinas e intersecciones por voz.
  - Invocación actualizada a `red movilidad` y skill manifest `Red Movilidad`.

- [ ] **Step 1: Escribir tests en `tests/test_handlers.py`**

Agregar tests a `tests/test_handlers.py`:

```python
@patch("src.red_service.format_dual_prediction_speech")
@patch("src.config.get_user_stops")
def test_prediccion_micro_intent_dual_stops(mock_stops, mock_speech):
    mock_stops.return_value = {
        "ida": {"code": "PD184", "name": "Avenida Grecia con Salvador"},
        "vuelta": {"code": "PD200", "name": "Avenida Grecia con Salvador"},
        "intersection": "Avenida Grecia con Salvador"
    }
    mock_speech.return_value = "Para la 513 en Avenida Grecia con Salvador..."

    req = {
        "type": "IntentRequest",
        "requestId": "r1",
        "timestamp": "2026-11-05T00:00:00Z",
        "locale": "es-ES",
        "intent": {
            "name": "PrediccionMicroIntent",
            "confirmationStatus": "NONE",
            "slots": {
                "linea": {"name": "linea", "value": "513"}
            }
        }
    }
    envelope = RequestEnvelope(request=req, context=Context(system=System(application=Application("app1"))))
    handler = PrediccionMicroIntentHandler()
    assert handler.can_handle(HandlerInput(request_envelope=envelope))
    resp = handler.handle(HandlerInput(request_envelope=envelope))
    assert "Para la 513 en Avenida Grecia con Salvador..." in resp.output_speech.ssml
```

- [ ] **Step 2: Ejecutar test para verificar que falla o requiere actualización**

Ejecutar:
```powershell
python -m pytest tests/test_handlers.py -k test_prediccion_micro_intent_dual_stops -v
```

- [ ] **Step 3: Actualizar `src/alexa_handlers.py`, los modelos de interacción y `skill.json`**

1. En `src/alexa_handlers.py`:
   - En `PrediccionMicroIntentHandler`:
     - Extraer `sentido_slot = slots.get("sentido")`.
     - Obtener `user_stops = config.get_user_stops(person_id=person_id)`.
     - Invocar `red_service.format_dual_prediction_speech(linea, user_stops["ida"], user_stops["vuelta"], user_stops.get("intersection"), sentido_query)`.
   - En `GuardarPreferenciaIntentHandler`:
     - Extraer slots `esquina`, `calleUno`, `calleDos`.
     - Si hay calles o esquina, resolver mediante `location_service.find_stops_by_intersection(calle1, calle2)` y guardar con `config.save_stops_pair()`.
     - Si solo se indica un paradero, buscar paradero opuesto con `location_service.find_opposing_stop(paradero)` y guardar ambos.
2. En `skill-package/interactionModels/custom/` (`es-ES.json`, `es-US.json`, `es-MX.json`):
   - Cambiar `"invocationName": "red movilidad"`.
   - Agregar slot type `SENTIDO_VIAJE` con valores `ida`, `vuelta`, `regreso`, `centro`, `casa`, `trabajo`.
   - Agregar slot `sentido` de tipo `SENTIDO_VIAJE` a `PrediccionMicroIntent`.
   - Agregar utterances: *"dónde viene la {linea} {sentido}"*, *"cuándo viene la {linea} de {sentido}"*, *"mi esquina es {calleUno} con {calleDos}"*.
3. En `skill-package/skill.json`:
   - Cambiar nombre de skill en cada locale a `"Red Movilidad"`.

- [ ] **Step 4: Ejecutar toda la suite de tests de handlers**

Ejecutar:
```powershell
python -m pytest tests/test_handlers.py -v
```
Resultado esperado: Todos los tests pasando.

- [ ] **Step 5: Commit de Task 4**

```bash
git add src/alexa_handlers.py skill-package/ tests/test_handlers.py
git commit -m "feat(alexa): update handlers and interaction models to Red Movilidad and dual stops"
```

---

### Task 5: Verificación Integral y Despliegue en Raspberry Pi

**Files:**
- Verification: Todo el repositorio
- Remote: `nowis@192.168.0.112:/home/nowis/alexa-red-movilidad/`

**Interfaces:**
- Verifica el funcionamiento end-to-end local y remoto en Raspberry Pi.

- [ ] **Step 1: Ejecutar suite de pruebas completa localmente**

Ejecutar:
```powershell
python -m pytest -v
```
Resultado esperado: 100% tests pasando (25+ tests).

- [ ] **Step 2: Sincronizar archivos modificados a Raspberry Pi**

Ejecutar vía SCP / SSH:
```powershell
scp -r src config.py skill-package tests nowis@192.168.0.112:/home/nowis/alexa-red-movilidad/
```

- [ ] **Step 3: Habilitar linger del usuario y reiniciar servicio systemd en Raspberry Pi**

Ejecutar vía SSH:
```powershell
ssh nowis@192.168.0.112 "sudo loginctl enable-linger nowis && systemctl --user restart alexa-red.service && systemctl --user status alexa-red.service --no-pager"
```
Resultado esperado: `alexa-red.service` en estado `active (running)` en el puerto 8000.

- [ ] **Step 4: Ejecutar pytest nativo en la Raspberry Pi**

Ejecutar vía SSH:
```powershell
ssh nowis@192.168.0.112 "cd /home/nowis/alexa-red-movilidad && venv/bin/python -m pytest -v"
```
Resultado esperado: 100% tests pasando en la Raspberry Pi.

- [ ] **Step 5: Probar endpoint público Tailscale Funnel con solicitud simulada de Alexa**

Ejecutar:
```powershell
curl.exe -X POST https://nowis.tail7d0b63.ts.net/alexa -H "Content-Type: application/json" -d "{\"version\":\"1.0\",\"session\":{\"new\":true,\"sessionId\":\"s1\",\"application\":{\"applicationId\":\"amzn1.ask.skill.2aa8d315-fc92-49e2-99e1-63943a4d2aef\"},\"user\":{\"userId\":\"u1\"}},\"request\":{\"type\":\"IntentRequest\",\"requestId\":\"r1\",\"timestamp\":\"2026-11-05T00:00:00Z\",\"intent\":{\"name\":\"PrediccionMicroIntent\",\"slots\":{\"linea\":{\"name\":\"linea\",\"value\":\"513\"}}}}}"
```
Resultado esperado: HTTP 200 OK con respuesta SSML conteniendo la llegada de la 513.

---

### Task 6: Publicación en Repositorio Público GitHub (`voice-assistants-red-movilidad`)

**Files:**
- Modify: `.gitignore` (verificar exclusiones)
- Git / GitHub CLI

**Interfaces:**
- CLI de GitHub (`gh`) y Git.

- [ ] **Step 1: Verificar exclusión estricta de secretos en `.gitignore`**

Revisar `.gitignore` para asegurar:
- `.env`
- `users.json`
- `stops.db` (o incluir si <50MB; verificar tamaño de stops.db)
- `venv/`, `__pycache__/`

Ejecutar:
```powershell
git status --ignored
```
Verificar que ni `.env` ni `users.json` aparezcan como archivos trackeados o sin ignorar.

- [ ] **Step 2: Autenticar `gh` CLI o configurar credenciales de GitHub**

Ejecutar:
```powershell
gh auth status
```
Si no está autenticado, ejecutar:
```powershell
gh auth login --web -h github.com
```

- [ ] **Step 3: Crear repositorio público en GitHub y asociar origen remoto**

Ejecutar:
```powershell
gh repo create voice-assistants-red-movilidad --public --source=. --remote=origin --push
```
Resultado esperado: Repositorio público creado en `https://github.com/saespinosac/voice-assistants-red-movilidad` y código pusheado a la rama `master`.

- [ ] **Step 4: Confirmar visibilidad y contenido en GitHub**

Ejecutar:
```powershell
gh repo view voice-assistants-red-movilidad --web
```
Verificar que el repositorio es público y contiene el código completo y la documentación sin secretos.
