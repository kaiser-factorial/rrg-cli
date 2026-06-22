from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .doctor import inspect_project
from .project import Project

HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>RRG</title><style>
:root{color-scheme:dark;--bg:#0f1115;--panel:#181b22;--line:#2a2f3a;--fg:#e6e9ef;--mut:#9aa3b2;--g:#3fb950;--b:#6ea8fe;--p:#a371f7;--bad:#f85149}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui}main{max-width:1050px;margin:auto;padding:24px}h1{font-size:20px}.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;margin:14px 0}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px;border-bottom:1px solid var(--line)}th,.mut{color:var(--mut)}.pill{display:inline-block;padding:2px 9px;border-radius:16px;font-weight:650;font-size:12px}.s1{background:#3fb95022;color:var(--g)}.s2{background:#6ea8fe22;color:var(--b)}.s3{background:#a371f733;color:var(--p)}.ok{color:var(--g)}.error{color:var(--bad)}code{color:var(--b)}</style></head>
<body><main><h1>RRG validation pipeline</h1><div id="app" class="card">Loading…</div></main>
<script>
const esc=s=>String(s??'').replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));
fetch('/api/status').then(r=>r.json()).then(d=>{let stages=d.stages.map((s,i)=>`<tr><td><span class="pill s${i+1}">${esc(s.id)}</span></td><td>${s.enabled?'enabled':'disabled'}</td><td>${esc(s.models.join(', ')||'—')}</td><td>${s.packages}</td></tr>`).join('');let checks=d.preflight.checks.filter(x=>x.severity!=='ok').map(x=>`<li class="${x.severity}">${esc(x.name)}: ${esc(x.detail)}</li>`).join('')||'<li class=ok>All checks passed</li>';document.getElementById('app').innerHTML=`<h2>${esc(d.project)}</h2><p class=mut><code>${esc(d.root)}</code></p><table><thead><tr><th>Stage</th><th>Status</th><th>Models</th><th>Packages</th></tr></thead><tbody>${stages}</tbody></table><h3>Preflight</h3><ul>${checks}</ul><p class=mut>The CLI remains authoritative for conversion, packaging, linting, prompts, and scorecards.</p>`}).catch(e=>document.getElementById('app').textContent=e);
</script></body></html>"""


def status(project: Project) -> dict[str, Any]:
    package_root = project.path_setting("packages", "operator/_packages")
    stages = []
    for stage_id in project.stage_ids():
        config = project.stage(stage_id)
        folder = package_root / stage_id
        stages.append(
            {
                "id": stage_id,
                "enabled": bool(config.get("enabled", True)),
                "models": [str(item.get("model")) for item in project.roster(stage_id)],
                "packages": len([path for path in folder.iterdir() if path.is_dir()]) if folder.is_dir() else 0,
            }
        )
    return {
        "project": project.name,
        "root": str(project.root),
        "stages": stages,
        "preflight": inspect_project(project, strict=True),
    }


def make_handler(project: Project):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/":
                payload, content_type = HTML.encode(), "text/html; charset=utf-8"
            elif self.path == "/api/status":
                payload = json.dumps(status(project), ensure_ascii=False).encode()
                content_type = "application/json"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format, *_args):
            return

    return Handler


def serve(project: Project, port: int = 8765, open_browser: bool = False) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(project))
    url = f"http://127.0.0.1:{port}"
    print(f"RRG GUI: {url}")
    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
