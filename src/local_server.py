import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import logging

from src.lambda_function import lambda_handler
from src import red_service
import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("local_server")

app = FastAPI(
    title="Alexa Red Movilidad & Bip! Gateway",
    description="Backend local y webhook para la Skill de Alexa de transporte en Santiago de Chile",
    version="1.0.0"
)


@app.api_route("/", methods=["GET", "POST"])
@app.api_route("/alexa", methods=["GET", "POST"])
async def alexa_endpoint(request: Request):
    """
    Endpoint Webhook para Alexa: responde tanto en / como en /alexa,
    soportando GET (healthcheck) y POST (solicitudes de Alexa).
    """
    if request.method == "GET":
        return {"status": "ok", "message": "Alexa Red Movilidad webhook endpoint activo"}

    try:
        req_json = await request.json()
        logger.info("Solicitud Alexa recibida")
        response_dict = lambda_handler(req_json, None)
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
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
