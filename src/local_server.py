import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
import logging

from src.lambda_function import lambda_handler
from src import red_service
from src import observability
import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("local_server")

app = FastAPI(
    title="Alexa Red Movilidad & Bip! Gateway",
    description="Backend local y webhook para la Skill de Alexa de transporte en Santiago de Chile",
    version="1.1.0"
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
        response_dict = lambda_handler(req_json, None)
        return JSONResponse(content=response_dict)
    except Exception as e:
        logger.error(f"Error procesando solicitud de Alexa: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/logs")
def get_logs(limit: int = 50):
    """Devuelve los eventos más recientes de observabilidad en formato JSON."""
    return observability.store.get_events(limit=limit)


@app.post("/api/logs/clear")
def clear_logs():
    """Limpia el buffer de eventos de observabilidad."""
    observability.store.clear()
    return {"status": "ok", "message": "Historial de observabilidad limpiado"}


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    """Dashboard web en tiempo real para visualizar peticiones de Alexa, latencia y respuestas habladas."""
    html = """<!DOCTYPE html>
<html lang="es" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Alexa Red Movilidad - Observabilidad en Vivo</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            redtrans: '#e11d48'
          }
        }
      }
    }
  </script>
  <style>
    @keyframes pulse-fast {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.4; transform: scale(0.9); }
    }
    .pulse-dot { animation: pulse-fast 1.8s infinite; }
  </style>
</head>
<body class="bg-gray-950 text-gray-100 min-h-screen font-sans antialiased">
  <div class="max-w-5xl mx-auto px-4 py-8">
    
    <!-- Header -->
    <header class="flex flex-col sm:flex-row sm:items-center sm:justify-between pb-6 border-b border-gray-800 gap-4">
      <div>
        <div class="flex items-center gap-3">
          <div class="w-3.5 h-3.5 rounded-full bg-emerald-500 pulse-dot shadow-lg shadow-emerald-500/50"></div>
          <h1 class="text-2xl font-bold tracking-tight bg-gradient-to-r from-red-400 via-rose-300 to-amber-200 bg-clip-text text-transparent">
            Red Movilidad Alexa
          </h1>
          <span class="px-2 py-0.5 text-xs font-semibold rounded bg-red-950/80 text-rose-300 border border-rose-800/40">
            En Vivo
          </span>
        </div>
        <p class="text-sm text-gray-400 mt-1">Observabilidad en tiempo real de peticiones, slots reconocidos y respuestas de voz.</p>
      </div>

      <div class="flex items-center gap-3">
        <button id="btn-refresh" onclick="fetchLogs()" class="px-3.5 py-1.5 text-xs font-medium bg-gray-800 hover:bg-gray-700 text-gray-200 rounded-lg border border-gray-700 transition">
          🔄 Refrescar
        </button>
        <button id="btn-clear" onclick="clearLogs()" class="px-3.5 py-1.5 text-xs font-medium bg-rose-950/60 hover:bg-rose-900/80 text-rose-300 rounded-lg border border-rose-800/50 transition">
          🗑️ Limpiar
        </button>
      </div>
    </header>

    <!-- Metrics Bar -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 my-6">
      <div class="bg-gray-900/80 border border-gray-800 rounded-xl p-4">
        <p class="text-xs uppercase tracking-wider text-gray-400 font-medium">Total Peticiones</p>
        <p id="metric-total" class="text-2xl font-bold text-white mt-1">0</p>
      </div>
      <div class="bg-gray-900/80 border border-gray-800 rounded-xl p-4">
        <p class="text-xs uppercase tracking-wider text-gray-400 font-medium">Latencia Promedio</p>
        <p id="metric-latency" class="text-2xl font-bold text-emerald-400 mt-1">0 ms</p>
      </div>
      <div class="bg-gray-900/80 border border-gray-800 rounded-xl p-4">
        <p class="text-xs uppercase tracking-wider text-gray-400 font-medium">Tasa de Éxito</p>
        <p id="metric-success" class="text-2xl font-bold text-emerald-400 mt-1">100%</p>
      </div>
      <div class="bg-gray-900/80 border border-gray-800 rounded-xl p-4">
        <p class="text-xs uppercase tracking-wider text-gray-400 font-medium">Última Petición</p>
        <p id="metric-last" class="text-sm font-semibold text-gray-300 mt-2 truncate">Esperando...</p>
      </div>
    </div>

    <!-- Logs Stream -->
    <main>
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-lg font-semibold text-gray-200">Historial de Interacciones de Voz</h2>
        <span id="sync-indicator" class="text-xs text-gray-400 flex items-center gap-1.5">
          <span class="inline-block w-2 h-2 rounded-full bg-emerald-500"></span> Actualizando cada 2s
        </span>
      </div>

      <div id="logs-container" class="space-y-4">
        <!-- Rendered dynamically -->
      </div>
    </main>

  </div>

  <script>
    let isFetching = false;

    async function fetchLogs() {
      if (isFetching) return;
      isFetching = true;
      try {
        const res = await fetch('/api/logs?limit=50');
        if (!res.ok) throw new Error('Error HTTP ' + res.status);
        const data = await res.json();
        renderLogs(data);
      } catch (err) {
        console.error('Error fetching logs:', err);
      } finally {
        isFetching = false;
      }
    }

    async function clearLogs() {
      if (!confirm('¿Deseas vaciar el historial de eventos?')) return;
      try {
        await fetch('/api/logs/clear', { method: 'POST' });
        fetchLogs();
      } catch (err) {
        console.error('Error clearing logs:', err);
      }
    }

    function timeAgo(dateString) {
      const now = new Date();
      const past = new Date(dateString);
      const diffSec = Math.floor((now - past) / 1000);
      if (diffSec < 5) return 'justo ahora';
      if (diffSec < 60) return `hace ${diffSec}s`;
      const diffMin = Math.floor(diffSec / 60);
      if (diffMin < 60) return `hace ${diffMin}m`;
      return past.toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    function renderLogs(events) {
      const container = document.getElementById('logs-container');
      
      // Update metrics
      document.getElementById('metric-total').textContent = events.length;
      if (events.length > 0) {
        const sumLatency = events.reduce((acc, e) => acc + (e.latency_ms || 0), 0);
        const avg = Math.round(sumLatency / events.length);
        const latElem = document.getElementById('metric-latency');
        latElem.textContent = `${avg} ms`;
        latElem.className = avg > 3000 ? 'text-2xl font-bold text-rose-400 mt-1' : (avg > 1500 ? 'text-2xl font-bold text-amber-400 mt-1' : 'text-2xl font-bold text-emerald-400 mt-1');

        const successCount = events.filter(e => e.status === 'success').length;
        const rate = Math.round((successCount / events.length) * 100);
        document.getElementById('metric-success').textContent = `${rate}%`;
        document.getElementById('metric-last').textContent = events[0].intent_name;
      } else {
        document.getElementById('metric-latency').textContent = '0 ms';
        document.getElementById('metric-success').textContent = '100%';
        document.getElementById('metric-last').textContent = 'Esperando...';
      }

      if (!events || events.length === 0) {
        container.innerHTML = `
          <div class="bg-gray-900/40 border border-gray-800/80 rounded-2xl p-12 text-center text-gray-500">
            <span class="text-4xl">🎙️</span>
            <p class="text-base font-medium text-gray-400 mt-3">Sin peticiones registradas aún</p>
            <p class="text-xs text-gray-500 mt-1">Dile a tu parlante: <em>«Alexa, pide a Red Movilidad qué micros me sirven para ir a Providencia»</em> y aparecerá aquí al instante.</p>
          </div>
        `;
        return;
      }

      container.innerHTML = events.map(ev => {
        const isErr = ev.status === 'error';
        const latClass = ev.latency_ms > 3500 
          ? 'bg-rose-950/80 text-rose-300 border-rose-800/50' 
          : (ev.latency_ms > 1500 ? 'bg-amber-950/80 text-amber-300 border-amber-800/50' : 'bg-emerald-950/80 text-emerald-300 border-emerald-800/50');
        
        const intentColor = ev.intent_name.includes('Route') 
          ? 'bg-blue-950 text-blue-300 border-blue-800' 
          : (ev.intent_name.includes('Saldo') ? 'bg-emerald-950 text-emerald-300 border-emerald-800' : 'bg-purple-950 text-purple-300 border-purple-800');

        const slotsHtml = ev.slots && Object.keys(ev.slots).length > 0
          ? Object.entries(ev.slots).map(([k, v]) => `
              <span class="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md bg-gray-800 border border-gray-700 text-gray-200">
                <span class="text-gray-400">${k}:</span> <strong class="text-amber-300 font-semibold">${v}</strong>
              </span>
            `).join(' ')
          : '<span class="text-xs text-gray-500 italic">Sin parámetros adicionales</span>';

        return `
          <div class="bg-gray-900 border ${isErr ? 'border-rose-800/60' : 'border-gray-800'} rounded-xl p-5 hover:border-gray-700 transition shadow-sm">
            <div class="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-gray-800/70">
              <div class="flex items-center gap-2">
                <span class="px-2.5 py-1 text-xs font-semibold rounded-md border ${intentColor}">
                  ${ev.intent_name}
                </span>
                <span class="text-xs text-gray-400">Usuario: <code class="text-gray-300">${ev.user_id}</code></span>
              </div>
              <div class="flex items-center gap-2">
                <span class="px-2 py-0.5 text-xs font-mono font-medium rounded border ${latClass}">
                  ⏱️ ${ev.latency_ms} ms
                </span>
                <span class="text-xs text-gray-400 font-mono" title="${ev.timestamp}">
                  ${timeAgo(ev.timestamp)}
                </span>
              </div>
            </div>

            <!-- Slots Recognized -->
            <div class="mt-3.5">
              <p class="text-xs uppercase tracking-wider text-gray-400 font-semibold mb-1.5">Slots / Parámetros Reconocidos:</p>
              <div class="flex flex-wrap gap-1.5">${slotsHtml}</div>
            </div>

            <!-- Output Speech -->
            <div class="mt-4 bg-gray-950/70 border border-gray-800/80 rounded-lg p-3.5">
              <p class="text-xs uppercase tracking-wider text-gray-400 font-semibold mb-1 flex items-center gap-1.5">
                <span>🔊</span> Respuesta Hablada de Alexa:
              </p>
              <p class="text-sm ${isErr ? 'text-rose-300 font-medium' : 'text-gray-200'} leading-relaxed">
                ${ev.speech ? `«${ev.speech}»` : '<span class="text-gray-500 italic">Sin audio devuelto</span>'}
              </p>
            </div>

            ${isErr && ev.error_detail ? `
              <div class="mt-3 bg-rose-950/40 border border-rose-900/60 rounded-lg p-3 text-xs font-mono text-rose-300">
                <strong>Error:</strong> ${ev.error_detail}
              </div>
            ` : ''}
          </div>
        `;
      }).join('');
    }

    // Auto-refresh every 2 seconds
    fetchLogs();
    setInterval(fetchLogs, 2000);
  </script>
</body>
</html>"""
    return html


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
