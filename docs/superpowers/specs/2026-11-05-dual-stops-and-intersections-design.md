# Especificación de Diseño: Paraderos Dobles por Sentido, Intersecciones Naturales y Publicación en GitHub

- **Fecha:** 2026-11-05
- **Proyecto:** `alexa-red-movilidad` ➔ `voice-assistants-red-movilidad`
- **Skill:** Red Movilidad (Invocación: `red movilidad`)
- **Estado:** Aprobado en Brainstorming (Pendiente de Plan e Implementación)

---

## 1. Resumen y Objetivos

El objetivo de esta actualización es evolucionar la Skill de Alexa para abordar la realidad urbana de Santiago de Chile: en cualquier calle o avenida existen **dos paraderos enfrentados** (uno de ida y uno de vuelta). El sistema debe permitir consultar micros sabiendo la **intersección exacta de calles** (ej: *"Avenida Grecia con Salvador"*) y el sentido de viaje, reduciendo la fricción al mínimo mediante configuración por voz inteligente.

Adicionalmente, se renombrará la Skill a **«Red Movilidad»** y se publicará el código fuente en GitHub como repositorio público bajo el nombre **`voice-assistants-red-movilidad`** utilizando la CLI de GitHub (`gh`).

---

## 2. Requerimientos Funcionales

### 2.1. Modelo de Paraderos Dobles (Ida y Vuelta)
- Cada usuario podrá tener asociados dos paraderos principales:
  - `ida`: Paradero en la vereda de salida habitual (ej. hacia el centro / trabajo).
  - `vuelta`: Paradero en la vereda contraria para el regreso (ej. hacia el barrio / casa).
- Compatibilidad retroactiva: si un usuario solo tiene un paradero configurado, se usa como predeterminado para ambos sentidos.

### 2.2. Limpiador y Formateador de Intersecciones (`clean_intersection_name`)
- La base de datos GTFS (`stops.db`) almacena nombres técnicos como:
  - `PC186-Avenida Apoquindo / Esq. El Bosque Norte`
  - `PA345-Parada 4 / (M) Universidad De Chile`
  - `PD184-Av. Grecia / Esq. Salvador`
- El formateador procesará y expandirá estas cadenas a lenguaje hablado natural:
  - Elimina código técnico y guión inicial (`PD184-`).
  - Expande abreviaciones: `Av.` ➔ *Avenida*, `Esq.` / `/` ➔ *con*, `(M)` ➔ *Metro*.
  - Resultado hablado: *«Avenida Grecia con Salvador»*, *«Avenida Apoquindo con El Bosque Norte»*.

### 2.3. Búsqueda y Emparejamiento Inteligente
- **Búsqueda por esquina:** El usuario puede dictar dos calles (ej. *«Grecia con Salvador»*). El sistema consulta en `stops.db` paraderos que contengan ambas calles y selecciona los dos paraderos más cercanos a esa esquina asignándolos a *ida* y *vuelta*.
- **Auto-emparejamiento:** Si el usuario dicta un solo código de paradero (ej. `PD184`), el sistema busca automáticamente el paradero opuesto más cercano (<60 m de distancia en la misma calle).

### 2.4. Diálogo de Consulta en Alexa
1. **Consulta general:** *«Alexa, pregúntale a Red Movilidad dónde viene la 513»*
   - Alexa consulta ambos paraderos y resume ambos sentidos:
     > *"Para el recorrido 513 en Avenida Grecia con Salvador: hacia el centro en el paradero PD184 viene a 4 minutos; y hacia Peñalolén en la vereda del frente (paradero PD200) viene a 9 minutos."*
2. **Consulta por sentido específico:** *«Alexa, pregúntale a Red Movilidad cuándo viene la 513 de ida»* (o *«hacia el centro»*)
   - Alexa responde únicamente el paradero correspondiente:
     > *"La 513 de ida viene en Avenida Grecia con Salvador (paradero PD184) a 1.200 metros, le faltan unos 5 minutos."*
3. **Resumen de Viaje:** *«Alexa, pregúntale a Red Movilidad si alcanzo a salir»*
   - Combina el saldo Bip! con los tiempos en ambos paraderos de su esquina habitual.

### 2.5. Configuración por Voz
- *«Alexa, dile a Red Movilidad que mi esquina es Grecia con Salvador»*
- *«Alexa, dile a Red Movilidad que mi paradero de ida es PD184 y el de vuelta es PD200»*
- *«Alexa, dile a Red Movilidad que mi paradero es PD184»* (con auto-detección del paradero opuesto).

### 2.6. Publicación en GitHub con `gh` CLI
- Crear el repositorio público `voice-assistants-red-movilidad`.
- Conectar el origen remoto y hacer push de la rama principal (`master` / `main`).
- Verificar que `.env` y `users.json` permanezcan estrictamente ignorados en `.gitignore`.

---

## 3. Arquitectura de Componentes y Cambios

### 3.1. `config.py` y `users.json`
- Estructura de `stops` en `users.json`:
  ```json
  "stops": {
    "ida": { "code": "PD184", "intersection": "Avenida Grecia con Salvador", "direction": "Hacia el centro" },
    "vuelta": { "code": "PD200", "intersection": "Avenida Grecia con Salvador", "direction": "Hacia Peñalolén" }
  }
  ```
- Funciones auxiliares añadidas:
  - `save_stops_pair(user_key, stop_ida, stop_vuelta, intersection_name)`
  - `get_user_stops(user_key)`

### 3.2. `src/location_service.py`
- `clean_intersection_name(raw_name: str) -> str`: Normaliza nombres de paraderos GTFS a nombres de esquinas en español natural.
- `find_stops_by_intersection(street1: str, street2: str) -> Tuple[Optional[dict], Optional[dict]]`: Encuentra los 2 paraderos opuestos en una intersección.
- `find_opposing_stop(stop_code: str) -> Optional[dict]`: Encuentra el paradero opuesto al código provisto por proximidad geográfica.

### 3.3. `src/red_service.py`
- Actualización de `format_prediction_speech`:
  - Acepta parámetros de paradero simple o dual (`stop_ida`, `stop_vuelta`, `sentido_query`).
  - Incluye la intersección hablada en la respuesta de voz.
- Actualización de `format_travel_summary_speech`:
  - Integra la lectura de ambos sentidos con el saldo Bip!.

### 3.4. `src/alexa_handlers.py`
- `PrediccionMicroIntentHandler`: Extrae slot de `sentido` (*"ida"*, *"vuelta"*, *"centro"*, *"casa"*). Si está presente, consulta solo ese paradero; si no, consulta ambos y genera el reporte consolidado.
- `GuardarPreferenciaIntentHandler`: Soporta slots de `esquina` / `interseccion` (o slots individuales `paraderoIda` y `paraderoVuelta`).

### 3.5. Modelos de Interacción (`es-ES.json`, `es-US.json`, `es-MX.json`)
- `invocationName`: `red movilidad`.
- Nuevos slots y tipos:
  - `SENTIDO_VIAJE`: Valores: `ida`, `vuelta`, `centro`, `casa`, `trabajo`, `regreso`.
  - Samples enriquecidos para consultas de ida y vuelta e intersecciones.

---

## 4. Estrategia de Pruebas y Verificación

1. **Tests unitarios del limpiador de intersecciones:**
   - Probar que `PC186-Avenida Apoquindo / Esq. El Bosque Norte` ➔ `Avenida Apoquindo con El Bosque Norte`.
   - Probar paradas de Metro: `PA345-Parada 4 / (M) Universidad De Chile` ➔ `Parada 4 de Metro Universidad de Chile`.
2. **Tests de emparejamiento de paraderos:**
   - Búsqueda por intersección `Grecia` y `Salvador` devuelve 2 paraderos.
   - Búsqueda del paradero opuesto de `PD184` devuelve el paradero de la vereda contraria.
3. **Tests de intents de Alexa:**
   - Consulta de micro sin sentido ➔ responde con ambos paraderos.
   - Consulta de micro de ida ➔ responde solo el paradero de ida.
   - Configuración de esquina por voz ➔ almacena ambos códigos.
4. **Pruebas de regresión:**
   - Ejecutar suite completa `pytest` y asegurar 100% de tests pasando en Windows y en la Raspberry Pi.

---

## 5. Publicación en GitHub

1. Verificar autenticación con `gh auth status` (o autenticar si es necesario).
2. Crear repositorio público:
   ```bash
   gh repo create voice-assistants-red-movilidad --public --source=. --remote=origin --push
   ```
3. Confirmar que los archivos sensibles (`.env`, `users.json`) no se encuentren en el árbol de commits.
