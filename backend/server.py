"""LitGraph server — pure Python stdlib, no framework dependencies.

Public:
  GET  /                    -> the single-page app (frontend/index.html)
  GET  /admin               -> the admin panel (frontend/admin.html)
  POST /api/analyze?mode=   -> build a literature graph (raw PDF body or JSON seed).
                               Optional "config" in the JSON body overrides the
                               preset per source: limits and sort order.
  GET  /api/config          -> public UI hints {has_key, default_mode, is_setup,
                               max_limits, sorts, presets}

Admin (password-protected via session cookie 'lit_session'):
  POST /api/admin/setup     -> first-run: set the admin password
  POST /api/admin/login     -> {password} -> sets session cookie
  POST /api/admin/logout
  GET  /api/admin/status    -> key/cache/usage info
  POST /api/admin/apikey    -> {api_key}
  POST /api/admin/settings  -> {default_mode}
  POST /api/admin/password  -> {current, new}
  POST /api/admin/clear-cache

Run:  python backend/server.py   then open http://localhost:8000
"""
import json
import os
import tempfile
import traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from urllib.parse import urlparse, parse_qs

from pdf_extract import extract as pdf_extract
from graph_builder import MAX_KEEP, MODES, build_graph_multi, expand_node
from sources import SORTS
import config

HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(HERE, "..", "frontend")
PORT = int(os.environ.get("PORT", "8000"))
PDF_NAME = "LitGraph-Documentation.pdf"


def _mask(key: str | None) -> str:
    if not key:
        return ""
    return (key[:4] + "…" + key[-4:]) if len(key) > 10 else "••••"


class Handler(BaseHTTPRequestHandler):
    # ---- low-level send -----------------------------------------------------
    def _send(self, code, body, ctype="application/json", extra_headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, name, ctype="text/html; charset=utf-8"):
        try:
            with open(os.path.join(FRONTEND, name), "rb") as f:
                self._send(200, f.read(), ctype)
        except FileNotFoundError:
            if name == PDF_NAME:
                self._send(404, {"error": "The PDF has not been built yet. Run "
                                          "tools/build_docs_pdf.py to generate it."})
                return
            self._send(404, {"error": f"{name} not found"})

    def log_message(self, fmt, *args):
        pass

    # ---- auth helpers -------------------------------------------------------
    def _session_token(self):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        c = SimpleCookie()
        c.load(raw)
        m = c.get("lit_session")
        return m.value if m else None

    def _is_admin(self):
        return config.valid_session(self._session_token())

    def _require_admin(self):
        if not self._is_admin():
            self._send(401, {"error": "Not authenticated."})
            return False
        return True

    def _body_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            return {}

    # ---- GET ----------------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._serve_file("index.html")
        elif path in ("/admin", "/admin.html"):
            self._serve_file("admin.html")
        elif path in ("/system", "/system.html"):
            self._serve_file("system.html")
        elif path in ("/docs", "/docs.html"):
            self._serve_file("docs.html")
        elif path == "/docs.pdf":
            # Pre-built from docs.html (tools/build_docs_pdf.py) so the runtime keeps
            # its two-dependency diet instead of shipping a PDF engine.
            self._serve_file(PDF_NAME, "application/pdf")
        elif path == "/health":
            self._send(200, {"ok": True})
        elif path == "/api/config":
            self._send(200, {
                "version": config.VERSION,
                "released": config.RELEASED,
                "has_key": bool(config.get_api_key()),
                "default_mode": config.get_settings()["default_mode"],
                "is_setup": config.is_password_set(),
                # The UI caps its own inputs with these so a limit that the API
                # would reject with a 400 can't be typed in the first place.
                "max_limits": MAX_KEEP,
                "sorts": list(SORTS),
                "presets": MODES,
            })
        elif path == "/api/admin/status":
            if not self._require_admin():
                return
            key = config.get_api_key()
            self._send(200, {
                "has_key": bool(key),
                "key_masked": _mask(key),
                "key_source": "config" if config.load().get("s2_api_key")
                              else ("env" if key else "none"),
                "cache": config.cache_stats(),
                "usage": config.STATS,
                "settings": config.get_settings(),
            })
        else:
            self._send(404, {"error": "not found"})

    # ---- POST ---------------------------------------------------------------
    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/analyze":
                return self._analyze()
            if path == "/api/extract":
                return self._extract()
            if path == "/api/expand":
                return self._expand()
            if path == "/api/admin/setup":
                return self._admin_setup()
            if path == "/api/admin/login":
                return self._admin_login()
            if path == "/api/admin/logout":
                return self._admin_logout()
            if path == "/api/admin/apikey":
                return self._admin_apikey()
            if path == "/api/admin/settings":
                return self._admin_settings()
            if path == "/api/admin/password":
                return self._admin_password()
            if path == "/api/admin/clear-cache":
                return self._admin_clear_cache()
            self._send(404, {"error": "not found"})
        except ValueError as e:
            self._send(422, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    # ---- analyze (one or many seeds) ----------------------------------------
    def _analyze(self):
        qs = parse_qs(urlparse(self.path).query)
        mode = (qs.get("mode", ["deep"])[0]).lower()
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        ctype = (self.headers.get("Content-Type") or "").lower()
        cfg = None
        if "application/pdf" in ctype or "octet-stream" in ctype:
            info = self._from_pdf(body)
            seeds = [{"arxiv_id": info.get("arxiv_id"), "title": info.get("title")}]
        else:
            data = json.loads(body or b"{}")
            cfg = data.get("config") if isinstance(data.get("config"), dict) else None
            if isinstance(data.get("seeds"), list) and data["seeds"]:
                seeds = data["seeds"]
            else:
                seeds = [{"arxiv_id": data.get("arxiv_id"),
                          "title": data.get("title"), "query": data.get("query")}]
        seeds = [s for s in seeds
                 if any(s.get(k) for k in ("arxiv_id", "title", "query"))]
        if not seeds:
            self._send(400, {"error": "No paper given. Upload a PDF or provide an "
                                      "arXiv id / title."})
            return
        self._send(200, build_graph_multi(seeds, mode=mode, cfg=cfg))

    def _extract(self):
        """Extract {arxiv_id, title} from an uploaded PDF (used to add it to a
        batch as a chip). Send the PDF as the raw request body."""
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        info = self._from_pdf(body)
        self._send(200, {"arxiv_id": info.get("arxiv_id"),
                         "title": info.get("title")})

    def _expand(self):
        """Grow the graph from an existing node. Body: {"id","type","config"?}."""
        data = self._body_json()
        node_id = data.get("id")
        kind = data.get("type", "paper")
        cfg = data.get("config") if isinstance(data.get("config"), dict) else None
        if not node_id:
            self._send(400, {"error": "Missing node id."})
            return
        self._send(200, expand_node(node_id, kind, cfg=cfg))

    @staticmethod
    def _from_pdf(body: bytes) -> dict:
        if not body:
            raise ValueError("That upload was empty. Please choose a PDF file.")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            tf.write(body)
            path = tf.name
        try:
            return pdf_extract(path)
        except ValueError:
            raise
        except Exception as e:  # noqa: BLE001
            # pypdf raises its own family of errors on anything malformed. A bad
            # upload is the user's mistake, not a server fault -- 422, not 500.
            raise ValueError(
                "Couldn't read that as a PDF — it may be corrupted or not a PDF at "
                "all. Try another file, or paste the arXiv id instead."
            ) from e
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    # ---- admin --------------------------------------------------------------
    def _admin_setup(self):
        if config.is_password_set():
            self._send(409, {"error": "Password already set. Please log in."})
            return
        pw = (self._body_json().get("password") or "").strip()
        if len(pw) < 6:
            self._send(422, {"error": "Password must be at least 6 characters."})
            return
        config.set_password(pw)
        token = config.create_session()
        self._send(200, {"ok": True}, extra_headers=self._cookie(token))

    def _admin_login(self):
        pw = (self._body_json().get("password") or "").strip()
        if not config.verify_password(pw):
            self._send(401, {"error": "Incorrect password."})
            return
        token = config.create_session()
        self._send(200, {"ok": True}, extra_headers=self._cookie(token))

    def _admin_logout(self):
        config.destroy_session(self._session_token())
        self._send(200, {"ok": True}, extra_headers={
            "Set-Cookie": "lit_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"})

    def _admin_apikey(self):
        if not self._require_admin():
            return
        key = (self._body_json().get("api_key") or "").strip()
        config.set_api_key(key or None)
        self._send(200, {"ok": True, "has_key": bool(config.get_api_key()),
                         "key_masked": _mask(config.get_api_key())})

    def _admin_settings(self):
        if not self._require_admin():
            return
        config.set_settings(default_mode=self._body_json().get("default_mode"))
        self._send(200, {"ok": True, "settings": config.get_settings()})

    def _admin_password(self):
        if not self._require_admin():
            return
        data = self._body_json()
        if not config.verify_password((data.get("current") or "").strip()):
            self._send(401, {"error": "Current password is incorrect."})
            return
        new = (data.get("new") or "").strip()
        if len(new) < 6:
            self._send(422, {"error": "New password must be at least 6 characters."})
            return
        config.set_password(new)
        self._send(200, {"ok": True})

    def _admin_clear_cache(self):
        if not self._require_admin():
            return
        removed = config.clear_cache()
        self._send(200, {"ok": True, "removed": removed})

    @staticmethod
    def _cookie(token):
        return {"Set-Cookie": f"lit_session={token}; Path=/; Max-Age={config.SESSION_TTL}; "
                              "HttpOnly; SameSite=Lax"}


def main():
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"LitGraph running -> http://localhost:{PORT}   (admin at /admin)")
    print("  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
