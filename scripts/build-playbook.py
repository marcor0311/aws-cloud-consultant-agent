"""Build an offline review HTML from the actual locally exported deliverables."""

import argparse
import base64
import json
import os
from html import escape
from pathlib import Path
from urllib.parse import quote

import pymupdf

ROOT = Path(__file__).resolve().parents[1]


def build(directory, destination, transcript_path=None):
    directory, destination = Path(directory), Path(destination)
    if transcript_path is None:
        transcript_path = directory / "fuentes/transcript.json"
        if directory.resolve() == ROOT / "insumos temporales de agente 1":
            transcript_path = (
                ROOT / "project/backend/fixtures/nike-lindora-stuart/transcript.json"
            )
    transcript = json.loads(Path(transcript_path).read_text())
    project_name = escape(transcript["project_name"], quote=True)
    documents = {}
    for key, name in (
        ("ficha", "ficha-proyecto.pdf"),
        ("resumen", "resumen-reunion.pdf"),
    ):
        with pymupdf.open(directory / name) as pdf:
            documents[key] = [
                "data:image/jpeg;base64,"
                + base64.b64encode(
                    page.get_pixmap(matrix=pymupdf.Matrix(1.7, 1.7)).tobytes(
                        "jpg", jpg_quality=92
                    )
                ).decode()
                for page in pdf
            ]
    fonts = ROOT / "project/backend/app/integrations/insumos_assets/fonts"
    font_css = "".join(
        f"@font-face{{font-family:Lato;font-weight:{weight};src:url(data:font/ttf;base64,"
        + base64.b64encode((fonts / name).read_bytes()).decode()
        + ") format('truetype');font-display:swap}"
        for name, weight in (("Lato-Regular.ttf", 400), ("Lato-Bold.ttf", 700))
    )
    deck = (directory / "presentacion.html").read_text()
    html = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>No Name / Documentos de proyecto</title><style>
@@FONTS@@
/* === REVIEW WORKSPACE === */
:root{color-scheme:light;--ink:#171918;--sub:#59616d;--rule:#d8dde5;--blue:#244cdd;--orange:#ed7531}*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;background:#f4f5f7;color:var(--ink);font-family:Lato,sans-serif}button,a{font:inherit}button{cursor:pointer}a{color:inherit}button:focus-visible,a:focus-visible{outline:3px solid var(--blue);outline-offset:4px}.workspace{max-width:1600px;margin:auto;padding:28px 35px 40px}.heading{display:flex;align-items:center;justify-content:space-between;gap:30px;border-bottom:1px solid var(--rule);padding-bottom:24px}.brand{font-size:25px;letter-spacing:-.8px;font-weight:700;display:flex;align-items:center;gap:12px}.brand svg{height:27px;width:27px}.heading p{font-size:12px;color:var(--sub);margin:0}.project{text-align:right}.project strong{display:block;font-size:15px;font-weight:700;margin-bottom:6px}.intro{margin:28px 0 24px;display:flex;justify-content:space-between;align-items:end}.intro h1{font-size:28px;letter-spacing:-.7px;margin:0 0 8px}.intro p{font-size:13px;color:var(--sub);margin:0}.intro .edition{font-size:11px;color:var(--sub)}.toolbar{display:flex;align-items:center;justify-content:space-between;gap:20px;background:#fff;padding:0 21px;border:1px solid var(--rule);border-bottom:0}.tabs{display:flex;gap:26px}.tabs button{border:0;background:none;color:var(--sub);font-size:13px;padding:20px 0 17px;border-bottom:3px solid transparent}.tabs button[aria-selected=true]{color:var(--ink);border-bottom-color:var(--blue);font-weight:700}.download{font-size:12px;color:var(--sub);text-decoration:none}.download:hover{color:var(--blue)}.viewer{border:1px solid var(--rule);background:#e9edf2;min-height:400px;padding:30px;display:flex;justify-content:center}.viewer.presentation{display:block;padding:0;background:#fff;aspect-ratio:16/9;min-height:0}.viewer iframe{display:block;width:100%;height:100%;border:0;aspect-ratio:16/9;background:#fff}.page-image{display:block;width:min(100%,795px);height:auto;align-self:flex-start;box-shadow:0 5px 20px #26344b15}.controls{display:flex;justify-content:space-between;align-items:center;padding:13px 0;border-bottom:1px solid var(--rule);font-size:11px;color:var(--sub)}.pages{display:flex;align-items:center;gap:15px}.pages button{border:1px solid var(--rule);background:#fff;color:var(--ink);width:33px;height:30px}.pages button:disabled{opacity:.3;cursor:default}.bottom{display:flex;justify-content:space-between;gap:30px;margin-top:20px;font-size:11px;line-height:1.7;color:var(--sub)}.bottom a{text-underline-offset:3px}.footmark{height:4px;width:50px;background:var(--orange);margin-top:24px}
</style></head><body><main class="workspace"><header class="heading"><div class="brand"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M5 27V5h7l15 22V5" fill="none" stroke="currentColor" stroke-width="4"/></svg>No Name</div><p>Consultoría digital</p><div class="project"><strong>@@PROJECT@@</strong><p>Encuadre ejecutivo</p></div></header><div class="intro"><div><h1>Documentos de proyecto</h1><p>Alcance, inversión, calendario y responsabilidad de entrega</p></div><span class="edition">Caso ficticio / Para revisión</span></div><div class="toolbar"><nav class="tabs" role="tablist" aria-label="Documentos"><button role="tab" id="tab-ficha" aria-controls="viewer" data-kind="ficha" aria-selected="false" tabindex="-1">Ficha del proyecto</button><button role="tab" id="tab-resumen" aria-controls="viewer" data-kind="resumen" aria-selected="false" tabindex="-1">Resumen de reunión</button><button role="tab" id="tab-presentacion" aria-controls="viewer" data-kind="presentacion" aria-selected="true">Presentación</button></nav><a class="download" id="download" href="../../insumos/presentacion.html" download>Descargar HTML ↓</a></div><section class="viewer presentation" id="viewer" role="tabpanel" aria-labelledby="tab-presentacion" tabindex="0"></section><div class="controls"><span id="format">Presentación ejecutiva / Formato panorámico</span><div class="pages" id="pages" hidden><button id="prev" aria-label="Página anterior">←</button><span id="counter" aria-live="polite"></span><button id="next" aria-label="Página siguiente">→</button></div><span id="deck-help">Haz clic en la presentación para navegar con las flechas</span></div><footer class="bottom"><span>No Name<br>Consultoría digital</span><span id="source-note">Para Junta Directiva y vicepresidencias<br>Conocimiento y seguimiento ejecutivo</span><span><a href="../../insumos/ficha-proyecto.pdf">Abrir ficha del proyecto</a><br><a href="../../insumos/resumen-reunion.pdf">Abrir resumen de reunión</a></span></footer><div class="footmark" aria-hidden="true"></div></main><template id="deck-template"><iframe title="Presentación ejecutiva de @@PROJECT@@" srcdoc="@@DECK@@"></iframe></template><script>
/* === ACTUAL EXPORTED DOCUMENTS === */
const documents=@@DOCUMENTS@@;const $=s=>document.querySelector(s);let kind='presentacion',current=0;
const labels={ficha:'Ficha del proyecto',resumen:'Resumen de reunión',presentacion:'Presentación'};
const files={ficha:'ficha-proyecto.pdf',resumen:'resumen-reunion.pdf',presentacion:'presentacion.html'};
function render(){document.querySelectorAll('[data-kind]').forEach(b=>{const selected=b.dataset.kind===kind;b.setAttribute('aria-selected',selected);b.tabIndex=selected?0:-1});$('#viewer').setAttribute('aria-labelledby','tab-'+kind);$('#viewer').classList.toggle('presentation',kind==='presentacion');$('#pages').hidden=kind==='presentacion';$('#deck-help').hidden=kind!=='presentacion';$('#download').href='../../insumos/'+files[kind];$('#download').textContent=kind==='presentacion'?'Descargar HTML ↓':'Descargar PDF ↓';if(kind==='presentacion'){$('#viewer').replaceChildren($('#deck-template').content.cloneNode(true));$('#format').textContent='Presentación ejecutiva / Formato panorámico'}else{const image=new Image();image.className='page-image';image.alt=labels[kind]+', página '+(current+1);image.src=documents[kind][current];$('#viewer').replaceChildren(image);$('#format').textContent=labels[kind]+' / Documento A4';$('#counter').textContent=(current+1)+' / '+documents[kind].length;$('#prev').disabled=current===0;$('#next').disabled=current===documents[kind].length-1}}
function change(value){kind=value;current=0;render();if(kind==='presentacion')$('#viewer').scrollIntoView({block:'center'})}
$('.tabs').addEventListener('click',e=>{const b=e.target.closest('[data-kind]');if(b)change(b.dataset.kind)});
$('.tabs').addEventListener('keydown',e=>{if(['ArrowRight','ArrowLeft','Home','End'].includes(e.key)){e.preventDefault();const keys=Object.keys(labels);const i=e.key==='Home'?0:e.key==='End'?2:(keys.indexOf(kind)+(e.key==='ArrowRight'?1:2))%3;change(keys[i]);$('#tab-'+kind).focus()}});
function move(delta){if(kind==='presentacion')return;current=Math.max(0,Math.min(documents[kind].length-1,current+delta));render()}
$('#prev').onclick=()=>move(-1);$('#next').onclick=()=>move(1);$('#viewer').addEventListener('keydown',e=>{if(['ArrowRight','ArrowLeft'].includes(e.key)){e.preventDefault();move(e.key==='ArrowRight'?1:-1)}});
render();
</script></body></html>"""
    html = html.replace("@@PROJECT@@", project_name)
    relative_directory = Path(
        os.path.relpath(directory.resolve(), destination.parent.resolve())
    ).as_posix()
    html = html.replace("../../insumos/", quote(relative_directory, safe="/.") + "/")
    html = html.replace("@@FONTS@@", font_css).replace(
        "@@DECK@@", escape(deck, quote=True)
    )
    html = html.replace("@@DOCUMENTS@@", json.dumps(documents, separators=(",", ":")))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html)
    print(f"Review HTML: {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    default_directory = ROOT / "insumos"
    temporary = ROOT / "insumos temporales de agente 1"
    if not (default_directory / "manifest.json").exists() and temporary.is_dir():
        default_directory = temporary
    parser.add_argument("--directory", type=Path, default=default_directory)
    parser.add_argument("--transcript", type=Path)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/design/playbook.html"
    )
    args = parser.parse_args()
    build(args.directory, args.output, args.transcript)
