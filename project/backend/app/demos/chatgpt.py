"""Local subscription-only proof: OAuth -> LangGraph -> meeting preparation.

Official flow: https://developers.openai.com/siwc/token-sharing-open-source/sign-in
Run with ``make chatgpt-demo``. Tokens live only in memory; no API-key fallback.
"""

import argparse
import json
import secrets
import time
import uuid
from threading import Lock
from typing import TypedDict
from urllib.parse import parse_qs

import httpx
import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from langgraph.graph import END, START, StateGraph
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import PROJECT_DIR, load_environment, private_path
from app.integrations.ai.oauth import DemoError, PlanConnection


class DemoState(TypedDict, total=False):
    transcript: str
    result: dict


def run_graph(connection, model, output_dir, progress=None):
    started = time.perf_counter()

    def load(_state):
        if progress:
            progress("reading", "Leyendo la transcripción de la reunión…")
        fixture = PROJECT_DIR / "backend/fixtures/preparation/tienda-deportiva.txt"
        return {"transcript": fixture.read_text(encoding="utf-8")}

    def prepare(state):
        if progress:
            progress("generating", "Esperando la primera respuesta del modelo…")
        return {"result": connection.generate(model, state["transcript"], progress)}

    graph = StateGraph(DemoState)
    graph.add_node("leer_transcripcion_ficticia", load)
    graph.add_node("preparar_con_suscripcion", prepare)
    graph.add_edge(START, "leer_transcripcion_ficticia")
    graph.add_edge("leer_transcripcion_ficticia", "preparar_con_suscripcion")
    graph.add_edge("preparar_con_suscripcion", END)
    state = graph.compile().invoke({})
    result = {
        **state["result"],
        "authentication": "chatgpt_plan_oauth",
        "status": "awaiting_stuart_review",
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    target = output_dir / uuid.uuid4().hex[:12]
    if progress:
        progress("saving", "Guardando el borrador para la revisión de Stuart…")
    target.mkdir(parents=True)
    (target / "transcript.md").write_text(state["transcript"], encoding="utf-8")
    (target / "preparation.md").write_text(result["draft"], encoding="utf-8")
    (target / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False)
    )
    return result, target


PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Preparación · Demo ChatGPT</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f5f6fa;color:#202537;font:16px/1.6 system-ui,sans-serif}
main{max-width:900px;margin:48px auto;padding:0 24px}header{display:flex;align-items:center;gap:12px;margin-bottom:40px}
.mark{background:#6554cf;color:white;border-radius:12px;padding:6px 13px;font-size:23px;font-weight:700}
.badge{margin-left:auto;background:#eae7fa;color:#5844ad;padding:4px 12px;border-radius:99px;font-size:12px;font-weight:600}
h1{font-size:clamp(26px,4vw,38px);line-height:1.2;letter-spacing:-1px;margin:0 0 12px}h2{font-size:23px;line-height:1.3;margin:0 0 12px}
p{margin:0 0 20px}.muted{color:#687087}.small{font-size:13px}.eyebrow{font-size:12px;letter-spacing:1.5px;color:#6554cf;font-weight:700;margin-bottom:12px}
.steps{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;padding:0;margin:32px 0 20px;list-style:none}
.steps li{border-top:3px solid #dfe2ec;padding-top:10px;color:#81889a;font-size:13px}.steps li.active{border-color:#6554cf;color:#5844ad;font-weight:700}.steps li.done{border-color:#23977d;color:#267d68}
.card{background:white;border:1px solid #e4e6ef;border-radius:20px;padding:36px;box-shadow:0 8px 30px #20253706;min-height:260px}
[hidden]{display:none!important}button,select{font:inherit;border-radius:10px;padding:12px 18px}button{background:#6554cf;color:white;border:0;cursor:pointer;font-weight:600}button:hover{background:#5140b1}button:disabled{opacity:.6;cursor:wait}
button:focus-visible,select:focus-visible,a:focus-visible{outline:3px solid #aba0ef;outline-offset:3px}select{background:#fafaff;border:1px solid #d6d9e5;width:100%;margin:0 0 20px;color:#202537}label{display:block;font-weight:600;margin-bottom:8px}
.spinner{width:44px;height:44px;border:4px solid #ece9fa;border-top-color:#6554cf;border-radius:50%;animation:spin 1s linear infinite;margin-bottom:22px}@keyframes spin{to{transform:rotate(360deg)}}
.activity{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:#687087;margin-top:24px}.dot{display:inline-block;width:7px;height:7px;background:#23977d;border-radius:50%;margin-right:6px}
.notice{background:#fff4e9;color:#854f1f;border:1px solid #f0d8ba;border-radius:12px;padding:16px;margin-bottom:20px}.success{display:inline-block;background:#e7f5ee;color:#24775b;border-radius:99px;padding:4px 12px;font-size:12px;font-weight:600;margin-bottom:18px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:15px/1.8 system-ui,sans-serif;background:#f7f8fc;border-radius:12px;padding:24px;margin:20px 0}footer{margin:20px 0;color:#80879a;font-size:12px}.ghost{background:#eeeaf9;color:#5844ad;margin-top:16px}.ghost:hover{background:#e2dbf6}
@media(max-width:600px){main{margin:24px auto;padding:0 16px}.card{padding:24px}.steps{gap:6px}.steps li{font-size:11px}header{margin-bottom:28px}}
@media(prefers-reduced-motion:reduce){.spinner{animation-duration:3s}}
</style></head><body><main>
<header><span class="mark" aria-hidden="true">P</span><strong>Preparación / Stuart</strong><span class="badge">DEMO LOCAL</span></header>
<p class="eyebrow">DESPUÉS DE LA REUNIÓN</p><h1>De la conversación al primer borrador.</h1>
<p class="muted">Conectá tu cuenta, elegí un modelo y dejá que el agente prepare los insumos.</p>
<ol class="steps" aria-label="Progreso"><li>01 · Conectar</li><li>02 · Elegir modelo</li><li>03 · Preparar</li><li>04 · Revisar</li></ol>
<div id="error" class="notice" role="alert" hidden></div>
<details id="partial" hidden><summary>Borrador parcial · Final sin confirmar</summary><pre id="partial-draft"></pre><p id="partial-report" class="small muted"></p></details>
<div id="network" class="notice" role="status" hidden>No se puede consultar la demo. Reintentando la conexión…</div>
<div class="card">
<section id="connect" hidden><h2>Conectá tu cuenta de ChatGPT</h2><p class="muted">La prueba utiliza tu suscripción mediante OAuth. Vas a iniciar sesión y revisar los permisos en OpenAI.</p>
<form method="post" action="/connect"><input type="hidden" name="csrf" value="__CSRF__"><button data-oai-siwc-button>Continue with ChatGPT</button></form></section>
<section id="choose" hidden><span class="success">Cuenta conectada</span><h2>Elegí con qué modelo preparar</h2><p class="muted">Usaremos la reunión ficticia de Tienda Deportiva Horizonte para crear el resumen, ideas y guion.</p>
<form method="post" action="/run"><input type="hidden" name="csrf" value="__CSRF__"><label for="model">Modelo de tu cuenta</label><select id="model" name="model" required></select><button>Preparar insumos con mi plan</button></form></section>
<section id="working" aria-busy="true"><div class="spinner" aria-hidden="true"></div><h2 id="work-title">Cargando el estado…</h2><p id="work-message" class="muted" role="status" aria-live="polite">Consultando la demo local.</p>
<div class="activity"><span id="elapsed"></span><span id="heartbeat"></span></div><p id="slow" class="small muted" hidden>La espera está tardando. Seguimos consultando el estado; recargar esta página no envía otra solicitud.</p>
<pre id="preview" aria-label="Borrador en curso" hidden></pre></section>
<section id="result" hidden><span class="success">Borrador listo · Pendiente de Stuart</span><h2>Ya tenés un punto de partida.</h2><p class="muted">La IA terminó la preparación. Ahora podés revisar y mejorar los insumos.</p><pre id="draft"></pre><details><summary class="small">Detalles de la prueba</summary><p id="report" class="small muted"></p></details><button id="again" class="ghost" type="button">Preparar de nuevo</button></section>
</div><footer>Transcripción ficticia · LangGraph + tu plan de ChatGPT · Sin API key</footer>
<noscript>Activá JavaScript para ver el progreso y el resultado de la demo.</noscript>
</main><script nonce="__NONCE__">
const $ = id => document.getElementById(id);
let state = {}, submitting = false;
function show(section) {
  ['connect','choose','working','result'].forEach(id => $(id).hidden = id !== section);
}
function steps(active) {
  document.querySelectorAll('.steps li').forEach((el,i) => {
    el.classList.toggle('active',i === active); el.classList.toggle('done',i < active);
    if(i === active) el.setAttribute('aria-current','step'); else el.removeAttribute('aria-current');
  });
}
function render(s) {
  state = s;
  $('error').hidden = s.phase !== 'error'; $('error').textContent = s.phase === 'error' ? s.message : '';
  $('partial').hidden = s.phase !== 'error' || !s.preview;
  $('partial-draft').textContent = s.preview; $('partial-report').textContent = s.report;
  const selected = $('model').value;
  $('model').replaceChildren(...s.models.map(m => { const el = document.createElement('option'); el.value=m.id; el.textContent=m.name; return el; }));
  if(s.models.some(m => m.id === selected)) $('model').value = selected;
  if(s.busy) {
    show('working'); steps(['verifying','catalog'].includes(s.phase) ? 0 : 2);
    $('work-title').textContent = ({verifying:'Conectando tu cuenta',catalog:'Buscando tus modelos',reading:'Leyendo la reunión',generating:'Preparando tus insumos',saving:'Guardando el borrador'})[s.phase] || 'Trabajando…';
    $('work-message').textContent = s.message;
    $('preview').textContent = s.preview; $('preview').hidden = !s.preview;
  } else if(s.phase === 'complete') {
    show('result'); steps(3); $('draft').textContent = s.draft; $('report').textContent = s.report;
  } else { show(s.connected ? 'choose' : 'connect'); steps(s.connected ? 1 : 0); }
  tick();
}
function tick() {
  if(!state.started_at || !state.busy) return;
  const elapsed = Math.max(0,Math.floor(Date.now()/1000 - state.started_at));
  const quiet = Math.max(0,Math.floor(Date.now()/1000 - state.last_event_at));
  $('elapsed').textContent = `${Math.floor(elapsed/60)}:${String(elapsed%60).padStart(2,'0')} transcurridos`;
  $('heartbeat').textContent = quiet < 3 ? '● Actividad recibida' : `Última señal del proceso hace ${quiet} s`;
  $('slow').hidden = quiet < 30;
}
async function poll() {
  try {
    const r = await fetch('/status',{cache:'no-store'});
    if(r.status === 403) { $('network').textContent = 'La demo se reinició. Recargá la página para abrir una sesión nueva.'; $('network').hidden=false; return; }
    if(!r.ok) throw new Error('status');
    render(await r.json()); $('network').hidden=true;
    if(state.busy) setTimeout(poll,1000);
  } catch (_) { $('network').hidden=false; setTimeout(poll,3000); }
}
document.querySelectorAll('form').forEach(form => form.addEventListener('submit', e => {
  if(submitting) { e.preventDefault(); return; } submitting=true;
  form.querySelector('button').disabled=true; show('working');
  const connecting = form.action.endsWith('/connect'); steps(connecting ? 0 : 2);
  $('work-title').textContent = connecting ? 'Abriendo OpenAI…' : 'Iniciando preparación…';
  $('work-message').textContent = connecting ? 'Vas a continuar en la página oficial para conectar tu cuenta.' : 'Estamos enviando la transcripción al agente.';
}));
$('again').addEventListener('click',() => { show('choose'); steps(1); });
window.addEventListener('pageshow',e => { if(e.persisted) location.reload(); });
setInterval(tick,1000); poll();
</script></body></html>"""


def create_app(connection, output_dir):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1"])
    csrf = secrets.token_urlsafe(32)
    cookie = secrets.token_urlsafe(32)
    script_nonce = secrets.token_urlsafe(24)
    lock = Lock()
    view = {
        "message": "Conectá tu cuenta para comprobar el consumo de tu plan.",
        "phase": "disconnected",
        "busy": False,
        "draft": "",
        "report": "",
        "preview": "",
        "started_at": None,
        "last_event_at": None,
    }

    def update(**values):
        with lock:
            view.update(values)

    def progress(phase, message, delta=""):
        with lock:
            view.update(phase=phase, message=message, last_event_at=time.time())
            if delta:
                view["preview"] = (view["preview"] + delta)[-12000:]

    @app.middleware("http")
    async def privacy(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        # no-referrer makes browser form POSTs send Origin: null, which our
        # same-origin guard correctly rejects. Keep local forms same-origin;
        # strip the referrer entirely only when leaving the OAuth callback.
        response.headers["Referrer-Policy"] = (
            "no-referrer" if request.url.path == "/auth/callback" else "same-origin"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; connect-src 'self'; "
            f"script-src 'nonce-{script_nonce}'; "
            "form-action 'self' https://auth.openai.com; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    async def form(request):
        values = parse_qs((await request.body()).decode())
        if (
            request.cookies.get("demo_session") != cookie
            or values.get("csrf", [""])[0] != csrf
            or request.headers.get("origin", str(request.base_url).rstrip("/"))
            != str(request.base_url).rstrip("/")
        ):
            raise HTTPException(
                403, "La sesión del formulario cambió. Abrí / y volvé a conectar."
            )
        return {key: values[0] for key, values in values.items()}

    @app.get("/", response_class=HTMLResponse)
    def index():
        content = PAGE.replace("__CSRF__", csrf).replace("__NONCE__", script_nonce)
        response = HTMLResponse(content)
        response.set_cookie("demo_session", cookie, httponly=True, samesite="lax")
        return response

    @app.get("/status")
    def status(request: Request):
        if request.cookies.get("demo_session") != cookie:
            raise HTTPException(403)
        with lock:
            snapshot = dict(view)
        # Explicit public data only: never serialize the connection or its tokens.
        return JSONResponse(
            {
                **snapshot,
                "connected": bool(
                    connection.access_token
                    and connection.models
                    and time.time() < connection.expires_at
                ),
                "models": connection.models,
            }
        )

    @app.post("/connect")
    async def connect(request: Request):
        await form(request)
        if view["busy"]:
            raise HTTPException(409)
        update(phase="authorizing", message="Completá la conexión en OpenAI.")
        return RedirectResponse(connection.authorize(), status_code=303)

    def finish_connection(params):
        try:
            connection.finish(params, progress)
            update(
                phase="ready",
                message="Tu cuenta está conectada. Elegí un modelo para continuar.",
            )
        except DemoError as error:
            update(phase="error", message=str(error))
        except (httpx.HTTPError, ValueError, KeyError):
            update(
                phase="error",
                message="No se pudo completar la conexión. Volvé a conectar tu cuenta.",
            )
        finally:
            update(busy=False)

    @app.get("/auth/callback")
    def callback(request: Request, tasks: BackgroundTasks):
        if request.cookies.get("demo_session") != cookie:
            raise HTTPException(403)
        if view["busy"]:
            raise HTTPException(409)
        update(
            busy=True,
            phase="verifying",
            started_at=time.time(),
            last_event_at=time.time(),
            message="Conectando con tu cuenta de ChatGPT…",
        )
        tasks.add_task(finish_connection, dict(request.query_params))
        # Return immediately so the page shows a loader during token exchange.
        return RedirectResponse("/", status_code=303)

    def failure(message):
        target = output_dir / f"incomplete-{uuid.uuid4().hex[:12]}"
        target.mkdir(parents=True)
        if connection.stream_text:
            (target / "preparation-partial.md").write_text(
                connection.stream_text, encoding="utf-8"
            )
        (target / "diagnostic.json").write_text(
            json.dumps(
                {
                    "status": "incomplete",
                    "authentication": "chatgpt_plan_oauth",
                    **connection.stream_diagnostic,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        update(
            phase="error",
            message=message,
            preview=connection.stream_text[-12000:],
            report=f"Diagnóstico y texto parcial: {target}",
        )

    def work(model):
        try:
            result, target = run_graph(connection, model, output_dir, progress)
            update(
                phase="complete",
                message="Prueba exitosa: tu suscripción generó el borrador desde LangGraph.",
                draft=result["draft"],
                report=f"Modelo: {model}. Archivos: {target}",
            )
            print(
                f"Generación completada con OAuth del plan. Resultado: {target}",
                flush=True,
            )
        except DemoError as error:
            failure(str(error))
        except (httpx.HTTPError, ValueError, KeyError, OSError):
            failure(
                "La prueba no se completó. Se conservó el texto recibido para revisarlo."
            )
        finally:
            update(busy=False)

    @app.post("/run")
    async def run(request: Request, tasks: BackgroundTasks):
        values = await form(request)
        if view["busy"]:
            raise HTTPException(409)
        model = values.get("model", "")
        if model not in {row["id"] for row in connection.models}:
            raise HTTPException(400, "Elegí un modelo disponible.")
        update(
            busy=True,
            phase="reading",
            started_at=time.time(),
            last_event_at=time.time(),
            message="LangGraph está preparando los insumos con tu plan…",
            draft="",
            report="",
            preview="",
        )
        tasks.add_task(work, model)
        return RedirectResponse("/", status_code=303)

    return app


def main():
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    with httpx.Client(timeout=120, follow_redirects=False) as client:
        connection = PlanConnection(
            client,
            private_path("chatgpt/plan-demo/registration.json"),
            f"http://127.0.0.1:{args.port}/auth/callback",
        )
        app = create_app(connection, PROJECT_DIR / "generated/chatgpt-plan-demo")
        print(f"Demo lista: http://127.0.0.1:{args.port}", flush=True)
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
