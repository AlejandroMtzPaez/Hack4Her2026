"""
web.py — Dashboard de "Always on Shelf"
=======================================
Servidor FastAPI que expone el Agente Universal y el Caso Supremo a traves de
una interfaz web, sin necesidad de tocar la terminal.

    python web.py
    -> abre http://localhost:8500

Lanza los scripts (agente_universal.py / caso_supremo.py) como subprocesos,
hace streaming de su salida en vivo por SSE, y senala el fin de la grabacion
creando un archivo runs/<run_id>.done cuando el usuario pulsa "Termine".

Requisitos:
    pip install fastapi uvicorn sse-starlette aiofiles
(y, para que el agente funcione: playwright + google-genai + python-dotenv,
 mas `python -m playwright install chromium` y una GEMINI_API_KEY).
"""
import os
import sys
import json
import asyncio
import threading
import subprocess
import datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

# El motor define los 5 procesos y la carpeta de skills. Importarlo es seguro:
# todo el codigo de arranque vive bajo `if __name__ == "__main__"`.
from agente_universal import PROCESOS, CARPETA_SKILLS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
RUNS_DIR = os.path.join(BASE_DIR, "runs")
SKILLS_DIR = os.path.join(BASE_DIR, CARPETA_SKILLS)
SESION_SUPREMO = os.path.join(BASE_DIR, "sesion_grabada.json")

os.makedirs(RUNS_DIR, exist_ok=True)
os.makedirs(SKILLS_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# Iconos para cada proceso (se usan en el frontend).
ICONOS = {
    "ordenes": "&#128196;",          # documento
    "facturacion": "&#129534;",      # recibo
    "alta_catalogo": "&#128230;",    # caja
    "catalogo_clientes": "&#128101;",# personas
    "compra_sitio": "&#128722;",     # carrito
}
# Que demuestra cada proceso (para el panel central).
DEMUESTRA = {
    "ordenes": "Captura ordenes de compra copiando de un portal externo a un ERP con estructura totalmente distinta.",
    "facturacion": "Convierte datos de un cliente en un CFDI, transformando identificadores y formatos sobre la marcha.",
    "alta_catalogo": "Da de alta productos en el catalogo interno leyendo una ficha de e-commerce.",
    "catalogo_clientes": "Migra perfiles de clientes desde un CRM externo al sistema interno.",
    "compra_sitio": "Identifica una requisicion y replica las acciones de compra en la tienda interna.",
}

app = FastAPI(title="Always on Shelf")

# Demo en localhost: sin restricciones de CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== ESTADO DE LOS SUBPROCESOS ====================
# run_id -> { "queue": asyncio.Queue, "proc": Popen, "done": bool, "rc": int|None }
RUNS = {}
_LOOP = None  # event loop principal, capturado en el primer /api/run


def _lanzar(run_id, cmd, extra_env=None):
    """Arranca el subproceso y vuelca su stdout linea-a-linea en la queue del run."""
    env = os.environ.copy()
    env["AOS_WEB"] = "1"            # senala a los scripts que no usen input()
    env["PYTHONUNBUFFERED"] = "1"   # salida sin buffer -> streaming en vivo
    env["PYTHONIOENCODING"] = "utf-8"
    if extra_env:
        env.update(extra_env)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=BASE_DIR,
        env=env,
        bufsize=1,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    RUNS[run_id]["proc"] = proc

    def _publicar(item):
        if _LOOP is not None:
            _LOOP.call_soon_threadsafe(RUNS[run_id]["queue"].put_nowait, item)

    def _leer():
        try:
            for linea in proc.stdout:
                _publicar({"type": "log", "linea": linea.rstrip("\n")})
        finally:
            proc.wait()
            RUNS[run_id]["done"] = True
            RUNS[run_id]["rc"] = proc.returncode
            _publicar({"type": "done", "ok": proc.returncode == 0})

    threading.Thread(target=_leer, daemon=True).start()


def _construir_cmd(body, run_id):
    """Traduce el modo del frontend al comando de terminal correspondiente."""
    modo = body.get("modo")
    py = [sys.executable, "-u"]   # -u = salida sin buffer
    proceso = body.get("proceso")
    registro = body.get("registro")
    objetivo = body.get("objetivo")
    flags = body.get("flags") or []

    if modo == "grabar":
        cmd = py + ["agente_universal.py", "grabar", proceso, "--web-mode", run_id]
    elif modo == "reproducir":
        # --web-mode tambien aqui: suprime el "ENTER para cerrar" final del script.
        cmd = py + ["agente_universal.py", "reproducir", proceso, registro, "--web-mode", run_id]
    elif modo == "lote":
        cmd = py + ["agente_universal.py", "lote", proceso, "--web-mode", run_id]
    elif modo == "limpiar":
        cmd = py + ["agente_universal.py", "limpiar", proceso, "--web-mode", run_id]
    elif modo == "supremo_objetivo":
        cmd = py + ["caso_supremo.py", objetivo or ""]
    elif modo == "supremo_grabar":
        cmd = py + ["caso_supremo.py", "grabar"]
    elif modo == "supremo_replicar":
        cmd = py + ["caso_supremo.py", "replicar"]
    else:
        return None
    # flags extra (ej. --local, --headless) anyadidos al final.
    cmd += [f for f in flags if isinstance(f, str)]
    return cmd


# ==================== ENDPOINTS ====================
@app.get("/")
async def index():
    idx = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(idx):
        return PlainTextResponse("Falta static/index.html", status_code=404)
    return FileResponse(idx)


@app.get("/api/skills")
async def api_skills():
    """Lista los 5 procesos con su estado de aprendizaje (skill grabado o no)."""
    salida = []
    for nombre, proc in PROCESOS.items():
        ruta = os.path.join(SKILLS_DIR, nombre + ".json")
        aprendido = os.path.exists(ruta)
        pasos = 0
        fecha = None
        titulo = proc["titulo"]
        if aprendido:
            try:
                with open(ruta, encoding="utf-8") as f:
                    s = json.load(f)
                pasos = len(s.get("pasos", []))
                titulo = s.get("titulo", titulo)
            except Exception:
                pass
            ts = os.path.getmtime(ruta)
            fecha = datetime.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")
        salida.append({
            "nombre": nombre,
            "titulo": titulo,
            "pasos": pasos,
            "aprendido": aprendido,
            "fecha": fecha,
        })
    return JSONResponse(salida)


@app.get("/api/procesos")
async def api_procesos():
    """Devuelve los 5 procesos con sus registros y metadatos para el frontend."""
    salida = []
    for nombre, proc in PROCESOS.items():
        salida.append({
            "nombre": nombre,
            "titulo": proc["titulo"],
            "icono": ICONOS.get(nombre, "&#9881;"),
            "demuestra": DEMUESTRA.get(nombre, ""),
            "registros": proc.get("registros", []),
            "demo": proc.get("demo"),
            "reproduce": proc.get("reproduce"),
        })
    return JSONResponse(salida)


@app.get("/api/supremo/sesion")
async def api_supremo_sesion():
    """Indica si existe una sesion grabada para el Caso Supremo (paso 2 del wizard)."""
    if not os.path.exists(SESION_SUPREMO):
        return JSONResponse({"existe": False})
    try:
        with open(SESION_SUPREMO, encoding="utf-8") as f:
            data = json.load(f)
        return JSONResponse({
            "existe": True,
            "productos": data.get("productos", []),
            "checkout": data.get("checkout", {}),
        })
    except Exception:
        return JSONResponse({"existe": False})


@app.post("/api/run")
async def api_run(request: Request):
    global _LOOP
    _LOOP = asyncio.get_running_loop()
    body = await request.json()

    # run_id determinista pero unico, sin depender de Date/random del sistema.
    run_id = "run_" + format(abs(hash((body.get("modo"), body.get("proceso"),
                                       body.get("registro"), body.get("objetivo"),
                                       id(body)))) % (10 ** 12), "012d")
    # Evita colisiones improbables.
    base = run_id
    i = 1
    while run_id in RUNS:
        run_id = base + "_" + str(i)
        i += 1

    cmd = _construir_cmd(body, run_id)
    if cmd is None:
        return JSONResponse({"error": "modo invalido: " + str(body.get("modo"))}, status_code=400)

    RUNS[run_id] = {"queue": asyncio.Queue(), "proc": None, "done": False, "rc": None}
    try:
        _lanzar(run_id, cmd)
    except FileNotFoundError as e:
        del RUNS[run_id]
        return JSONResponse({"error": "no se pudo lanzar: " + str(e)}, status_code=500)

    return JSONResponse({"run_id": run_id, "cmd": " ".join(cmd)})


@app.get("/api/stream/{run_id}")
async def api_stream(run_id: str, request: Request):
    """SSE: streaming de stdout del subproceso, linea a linea, hasta que termina."""
    if run_id not in RUNS:
        return JSONResponse({"error": "run_id desconocido"}, status_code=404)
    queue = RUNS[run_id]["queue"]

    async def gen():
        while True:
            if await request.is_disconnected():
                break
            try:
                item = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # latido para mantener viva la conexion y detectar desconexion
                yield {"event": "ping", "data": "{}"}
                continue
            if item["type"] == "done":
                yield {"event": "done", "data": json.dumps({"ok": item["ok"]})}
                break
            else:
                yield {"event": "log", "data": json.dumps({"linea": item["linea"]})}

    return EventSourceResponse(gen())


@app.post("/api/done/{run_id}")
async def api_done(run_id: str):
    """Crea runs/<run_id>.done para senalar al proceso 'grabar' que el usuario termino."""
    os.makedirs(RUNS_DIR, exist_ok=True)
    flag = os.path.join(RUNS_DIR, run_id + ".done")
    with open(flag, "w", encoding="utf-8") as f:
        f.write("done")
    return JSONResponse({"ok": True})


@app.delete("/api/skills/{nombre}")
async def api_borrar_skill(nombre: str):
    """Elimina el skill grabado de un proceso (el agente lo 'olvida')."""
    ruta = os.path.join(SKILLS_DIR, nombre + ".json")
    if not os.path.exists(ruta):
        return JSONResponse({"ok": False, "error": "no existe"}, status_code=404)
    os.remove(ruta)
    return JSONResponse({"ok": True})


# Sirve la carpeta static/ (assets adicionales si los hubiera).
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print(" Always on Shelf — Dashboard")
    print(" Abre:  http://localhost:8500")
    print("=" * 60)
    uvicorn.run(app, host="127.0.0.1", port=8500, log_level="info")
