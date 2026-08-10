from __future__ import annotations

import json
import logging
import secrets
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlparse

from .errors import RRGError
from .gui_service import GUIState
from .project import Project
from .workspace import WorkspaceState

MAX_REQUEST_BYTES = 2 * 1024 * 1024


def _asset(name: str) -> bytes:
    return files("rrg_cli").joinpath("web", name).read_bytes()


def status(project: Project) -> dict:
    """Compatibility helper used by integrations and tests."""
    return GUIState(project).bootstrap()


def make_handler(project: Project, token: str | None = None, workspace: str | None = None):
    state = WorkspaceState(project, workspace=workspace)
    session_token = token or secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        rrg_token = session_token

        def _send(self, status_code: int, payload: bytes, content_type: str) -> None:
            try:
                self.send_response(status_code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-src 'self'; base-uri 'none'; frame-ancestors 'none'",
                )
                self.end_headers()
                self.wfile.write(payload)
            except ConnectionError:
                # The client closed the connection before we finished writing — common when
                # the browser cancels an in-flight request (e.g. clicking through questions
                # faster than the figure payloads stream back). Nothing left to send.
                pass

        def _json(self, value, status_code: int = 200) -> None:
            self._send(status_code, json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _send_pdf(self, payload: bytes, content_type: str) -> None:
            # Served into an iframe on the same origin, so the page must be able to
            # frame it (frame-ancestors 'self'); everything else is locked down.
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Content-Disposition", "inline")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            try:
                self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'self'")
                self.end_headers()
                self.wfile.write(payload)
            except ConnectionError:
                pass

        def _authorized(self) -> bool:
            return secrets.compare_digest(self.headers.get("X-RRG-Token", ""), session_token)

        def _require_api_auth(self) -> bool:
            if self._authorized():
                return True
            self._json({"error": "invalid local GUI session"}, HTTPStatus.FORBIDDEN)
            return False

        def _query(self) -> tuple[str, dict[str, str]]:
            parsed = urlparse(self.path)
            values = {key: items[-1] for key, items in parse_qs(parsed.query).items() if items}
            return parsed.path, values

        def do_GET(self):  # noqa: N802
            path, query = self._query()
            try:
                if path == "/":
                    html = _asset("index.html").decode().replace("__RRG_TOKEN__", session_token)
                    return self._send(200, html.encode(), "text/html; charset=utf-8")
                if path == "/assets/app.css":
                    return self._send(200, _asset("app.css"), "text/css; charset=utf-8")
                if path == "/assets/app.js":
                    return self._send(200, _asset("app.js"), "text/javascript; charset=utf-8")
                if not path.startswith("/api/"):
                    return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                if path == "/api/origin/report.pdf":
                    # An iframe cannot send the auth header, so this stream accepts the
                    # session token via header or query param (local origin only).
                    token = self.headers.get("X-RRG-Token", "") or query.get("token", "")
                    if not secrets.compare_digest(token, session_token):
                        return self._json({"error": "invalid local GUI session"}, HTTPStatus.FORBIDDEN)
                    payload, content_type = state.origin_report_bytes()
                    return self._send_pdf(payload, content_type)
                if not self._require_api_auth():
                    return
                if path == "/api/bootstrap":
                    return self._json(state.bootstrap())
                if path == "/api/workspace":
                    return self._json(state.workspace_status())
                if path == "/api/preflight":
                    return self._json(state.preflight(stage=query.get("stage")))
                if path == "/api/prompt":
                    return self._json(state.render(query.get("stage", ""), query.get("model", ""), query.get("mode", "discuss")))
                if path == "/api/runs":
                    return self._json({"runs": state.runs()})
                if path == "/api/archive":
                    return self._json(state.list_archive())
                if path == "/api/tree":
                    return self._json(state.file_tree(query.get("xray") == "1"))
                if path == "/api/tree/file":
                    return self._json(state.tree_file(query.get("path", ""), query.get("xray") == "1"))
                if path == "/api/run":
                    return self._json(state.run_detail(query.get("run", "")))
                if path == "/api/file":
                    return self._json(state.run_file(query.get("run", ""), query.get("file", "")))
                if path == "/api/compare":
                    return self._json(state.compare(query.get("run", ""), int(query.get("question", "0"))))
                if path == "/api/scorecards":
                    return self._json({"scorecards": state.scorecards()})
                if path == "/api/grading":
                    return self._json(state.grading_overview(query.get("run", "")))
                if path == "/api/overview":
                    return self._json(state.cross_run_overview())
                if path == "/api/scorecard":
                    return self._json(state.scorecard_content(query.get("path", "")))
                if path == "/api/origin":
                    return self._json(state.origin_overview())
                if path == "/api/origin/report":
                    return self._json(state.origin_report())
                if path == "/api/origin/methodology_prompt":
                    return self._json(state.methodology_prompt())
                if path == "/api/origin/intake_prompt":
                    return self._json(state.intake_prompt())
                return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except RRGError as exc:
                return self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except (ValueError, KeyError) as exc:
                return self._json({"error": f"invalid request: {exc}"}, HTTPStatus.BAD_REQUEST)
            except Exception as exc:  # pragma: no cover - last-resort local UI boundary
                return self._json({"error": f"internal error: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def do_POST(self):  # noqa: N802
            path, _query = self._query()
            if not path.startswith("/api/"):
                return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            if not self._require_api_auth():
                return
            origin = self.headers.get("Origin")
            if origin and not (
                origin.startswith("http://127.0.0.1:") or origin.startswith("http://localhost:")
            ):
                return self._json({"error": "cross-origin write refused"}, HTTPStatus.FORBIDDEN)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > MAX_REQUEST_BYTES:
                    return self._json({"error": "request is too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                payload = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(payload, dict):
                    raise RRGError("request body must be a JSON object")
                if path == "/api/convert":
                    result = state.convert(payload)
                elif path == "/api/package":
                    result = state.package(payload)
                elif path == "/api/import":
                    result = state.import_run(payload)
                elif path == "/api/scorecard":
                    result = state.make_scorecard(payload)
                elif path == "/api/note":
                    result = {
                        "notes": state.save_note(
                            str(payload.get("run", "")),
                            int(payload.get("question", 0)),
                            str(payload.get("text", "")),
                        )
                    }
                elif path == "/api/setup":
                    result = state.save_setup(payload)
                elif path == "/api/origin/methodology":
                    result = {**state.save_methodology(str(payload.get("text", ""))), "origin": state.origin_overview()}
                elif path == "/api/origin/intake":
                    result = {**state.save_intake(str(payload.get("text", ""))), "origin": state.origin_overview()}
                elif path == "/api/grading/verdict":
                    result = state.save_verdict(
                        str(payload.get("run", "")),
                        int(payload.get("question", 0)),
                        str(payload.get("verdict", "")),
                        str(payload.get("note", "")),
                        bool(payload.get("confirmed")),
                    )
                elif path == "/api/grading/finalize":
                    result = state.finalize_grading(str(payload.get("run", "")))
                elif path == "/api/grading/reopen":
                    result = state.reopen_grading(str(payload.get("run", "")))
                elif path == "/api/grading/delete":
                    result = state.delete_grading(str(payload.get("run", "")))
                elif path == "/api/scorecard/delete":
                    result = state.delete_scorecard(str(payload.get("path", "")))
                elif path == "/api/grading/acknowledge-breach":
                    result = state.acknowledge_breach(str(payload.get("run", "")))
                elif path == "/api/archive/restore":
                    result = state.restore_archived(str(payload.get("id", "")))
                elif path == "/api/archive/purge":
                    result = state.purge_archived(str(payload.get("id", "")))
                elif path == "/api/project/select":
                    result = state.select_project(str(payload.get("root", "")))
                elif path == "/api/project/create":
                    result = state.create_project(
                        str(payload.get("path", "")),
                        str(payload.get("name", "")),
                    )
                else:
                    return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return self._json(result)
            except json.JSONDecodeError:
                return self._json({"error": "request body is not valid JSON"}, HTTPStatus.BAD_REQUEST)
            except RRGError as exc:
                return self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except (ValueError, KeyError) as exc:
                return self._json({"error": f"invalid request: {exc}"}, HTTPStatus.BAD_REQUEST)
            except Exception as exc:  # pragma: no cover
                return self._json({"error": f"internal error: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def log_message(self, _format, *_args):
            return

    return Handler


class _DropXrefNoise(logging.Filter):
    """Drop pypdf's benign 'Ignoring wrong pointing object N 0' xref warnings.

    These come from a slightly malformed cross-reference table in some PDFs; pypdf
    recovers fine (figures still extract). We drop only this exact message — every
    other pypdf warning, and any real error or exception, is left untouched.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return "wrong pointing object" not in record.getMessage()


def _quiet_pdf_xref_noise() -> None:
    logging.getLogger("pypdf._reader").addFilter(_DropXrefNoise())


def serve(
    project: Project,
    port: int = 8765,
    open_browser: bool = False,
    workspace: str | None = None,
) -> None:
    _quiet_pdf_xref_noise()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(project, workspace=workspace))
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
