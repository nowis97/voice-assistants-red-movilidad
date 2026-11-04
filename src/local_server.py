import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import logging

from src.lambda_function import sb
from src import red_service
import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("local_server")

app = FastAPI(
    title="Alexa Red Movilidad & Bip! Gateway",
    description="Backend local y webhook para la Skill de Alexa de transporte en Santiago de Chile",
    version="1.0.0"
)

# Skill instance
skill = sb.create()


@app.get("/")
def root():
    return {
        "status": "online",
        "service": "Alexa Red Movilidad Skill Backend",
        "endpoints": {
            "alexa_webhook": "/alexa",
            "test_saldo": "/api/saldo",
            "test_micro": "/api/micro",
            "test_gps": "/api/gps/401"
        }
    }


@app.get("/alexa")
def alexa_status():
    return {"status": "ok", "message": "Alexa Red Movilidad webhook endpoint activo"}


@app.post("/alexa")
async def alexa_endpoint(request: Request):
    """
    Endpoint Webhook HTTPS para conectar Alexa Developer Console directamente
    usando túneles como Cloudflare Tunnel o ngrok (HTTPS).
    """
    try:
        req_json = await request.json()
        logger.info("Solicitud Alexa recibida")
        response_dict = skill.invoke(req_json, None)
        return JSONResponse(content=response_dict)
    except Exception as e:
        logger.error(f"Error procesando solicitud de Alexa: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/saldo")
def api_saldo(card: str = None):
    """Prueba rápida de consulta de saldo Bip!."""
    return red_service.get_bip_balance(card)


@app.get("/api/micro")
def api_micro(paradero: str = None, linea: str = None):
    """Prueba rápida de predictivo de paraderos."""
    return red_service.get_stop_predictions(paradero, linea)


@app.get("/api/gps/{recorrido}")
def api_gps(recorrido: str):
    """Prueba de buses GPS activos en vivo."""
    return {"recorrido": recorrido, "buses": red_service.get_buses_on_route(recorrido)}


if __name__ == "__main__":
    uvicorn.run("src.local_server:app", host="0.0.0.0", port=config.PORT, reload=True)
