# Alexa Skill: Red Movilidad & Saldo Bip! 🚍💳🇨🇱

Skill personalizada para **Amazon Alexa** que permite consultar en tiempo real el saldo de tu tarjeta **Bip!** física y el tiempo estimado de llegada de micros de **Red Metropolitana de Movilidad** (Santiago de Chile).

---

## ✨ Características

* **💳 Consulta de Saldo Bip!:** Consulta en tiempo real el saldo exacto en CLP de tu tarjeta utilizando el endpoint oficial reverso de Red Movilidad (`/phone/v13/payment/balance`).
* **🚏 Predictivo de Micros ("¿Dónde viene y cuánto le falta?"):** Informa los minutos estimados de llegada, distancia en metros y patente del bus para cualquier paradero y recorrido (ej: paradero `PA345`, micro `401`).
* **🏃 Modo "Alcanzo a Salir" (Resumen de Viaje):** Combina el saldo de tu Bip y la llegada de tu micro habitual en una sola respuesta rápida de voz antes de salir de casa.
* **🛰️ Buses en Ruta (Telemetría GPS en Vivo):** Informa la cantidad de máquinas activas circulando en el recorrido mediante telemetría satelital directa.
* **⚡ Configuración de Favoritos:** Configura tu tarjeta y tu paradero habitual en variables de entorno para no tener que dictar números ni códigos por voz cada vez.
* **☁️ Dual-Deploy:** Funciona en **AWS Lambda** (100% serverless, gratis) o en tu propia **PC/Servidor local** con FastAPI y Cloudflare Tunnel/ngrok.

---

## 🗣️ Comandos de Voz de Ejemplo

| Lo que dices | Lo que responde Alexa |
| :--- | :--- |
| *«Alexa, abre Red Micro»* | Saludo y menú de ayuda de la skill. |
| *«Alexa, pregúntale a Red Micro cuánto saldo tengo»* | *"Tu tarjeta Bip tiene un saldo de 3.450 pesos."* |
| *«Alexa, pregúntale a Red Micro cuánto le falta a la 401»* | *"La micro 401 le faltan entre 4 y 7 minutos, viene a 1.200 metros."* |
| *«Alexa, pregúntale a Red Micro cuándo viene la micro»* | Consulta tu paradero y recorrido habitual por defecto. |
| *«Alexa, pregúntale a Red Micro si alcanzo a salir»* | *"La 401 viene a 800 metros, le faltan unos 5 minutos. Tu saldo Bip es de 2.800 pesos."* |
| *«Alexa, pregúntale a Red Micro cuántos buses hay en la 401»* | *"Hay 34 buses del recorrido 401 circulando en este momento en Santiago."* |
| *«Alexa, dile a Red Micro que guarde mi tarjeta 12345678»* | Configuración de tarjeta Bip por voz al instante. |

---

## 📁 Estructura del Proyecto

```
alexa-red-movilidad/
├── config.py                 # Parámetros por defecto (Bip, paradero, recorrido)
├── requirements.txt          # Dependencias (ask-sdk-core, fastapi, requests)
├── .env.example              # Plantilla de variables de entorno
├── src/
│   ├── red_service.py        # Conexión con APIs de Red Movilidad y Bip
│   ├── alexa_handlers.py     # Manejadores de Intents de Alexa ASK SDK
│   ├── lambda_function.py    # Handler de entrada para AWS Lambda
│   └── local_server.py       # Servidor FastAPI para pruebas locales o Webhook
├── skill-package/
│   ├── skill.json            # Manifiesto oficial de la Skill
│   └── interactionModels/
│       └── custom/
│           └── es-ES.json    # Modelo de voz e intenciones en español
└── tests/
    ├── test_red_service.py   # Tests de integración contra las APIs
    └── test_handlers.py      # Tests unitarios del pipeline de Alexa
```

---

## 🚀 Puesta en Marcha Rápida

### 1. Clonar e Instalar Dependencias

```bash
cd alexa-red-movilidad
cp .env.example .env
pip install -r requirements.txt
```

Edita tu archivo `.env` con tus datos habituales:
```ini
DEFAULT_BIP_NUMBER=12345678    # Tu número de tarjeta física (8 dígitos)
DEFAULT_STOP_CODE=PA345        # Código de tu paradero más cercano
DEFAULT_SERVICE=401            # Tu micro favorita (ej: 401, 506, B02)
```

### 2. Probar que las APIs y Tests funcionen

```bash
python -m pytest tests/ -v
```
*(Deberías ver los 12 tests pasando con éxito).*

---

## 🛠️ Configuración en Alexa Developer Console

1. Entra a [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask).
2. Haz clic en **Create Skill**:
   * **Skill name:** `Red Micro`
   * **Primary locale:** `Spanish (ES)` o `Spanish (MX / US)`.
   * **Model:** `Custom`
   * **Hosting:** `Provision your own` (AWS Lambda o Webhook).
3. En el menú lateral, ve a **Interaction Model > JSON Editor**.
4. Copia y pega el contenido completo de [`skill-package/interactionModels/custom/es-ES.json`](skill-package/interactionModels/custom/es-ES.json).
5. Haz clic en **Save Model** y luego en **Build Model**.

---

## 🌐 Opciones de Despliegue

### Opción A: AWS Lambda (Recomendada, 100% Gratis)

1. En la consola de AWS, crea una función Lambda:
   * **Runtime:** Python 3.11 o 3.12.
   * **Architecture:** x86_64 o arm64.
2. Agrega el desencadenador (Trigger) **Alexa Skills Kit** y pega el Skill ID.
3. Empaqueta el código junto con las librerías:
   ```bash
   pip install -r requirements.txt -t package/
   cp -r src config.py package/
   cd package && zip -r ../lambda.zip .
   ```
4. Sube el `.zip` a Lambda y configura el Handler: `src.lambda_function.lambda_handler`.
5. En variables de entorno de Lambda añade `DEFAULT_BIP_NUMBER`, `DEFAULT_STOP_CODE` y `DEFAULT_SERVICE`.
6. Copia el **ARN** de la función Lambda y pégalo en la sección **Endpoint** de la Alexa Developer Console.

### Opción B: Servidor Local / Webhook con Cloudflare Tunnel o ngrok

Si prefieres ejecutar el backend en tu PC o servidor doméstico:

1. Inicia el servidor FastAPI:
   ```bash
   python -m src.local_server
   ```
2. Expone el puerto local (por defecto 8000) con Cloudflare Tunnel o ngrok:
   ```bash
   ngrok http 8000
   ```
3. En la Alexa Developer Console > **Endpoint**:
   * Selecciona **HTTPS**.
   * Pega la URL generada: `https://tu-dominio.ngrok-free.app/alexa`.
   * Selecciona el certificado SSL comodín (*"My development endpoint is a sub-domain of a domain that has a wildcard certificate"*).
4. Guarda y ¡listo! Ya puedes probar la skill desde la pestaña **Test** o directo en tus parlantes Echo físicos asociados a tu cuenta.

---

## 📄 Licencia

MIT. Proyecto educativo y de código abierto para la comunidad de usuarios de transporte público en Santiago de Chile.
