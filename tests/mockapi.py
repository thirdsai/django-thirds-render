"""A local stand in for the thirds.ai API, used by the mocked suite only.

POST /v1/pdf and /v1/image answer 202 queued; the first GET answers succeeded (or failed
when the request data holds MOCKFAIL, or stays running when reference is MOCKSLOW).
Downloads need no key. When THIRDS_OPENAPI_SPEC points at the public OpenAPI file and
jsonschema is installed, every POST body is validated against PdfRequest or ImageRequest.
"""

import json
import os
import secrets
import struct
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MOCK_KEY = "mock-key-not-a-secret"


def png_bytes(w, h):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x11\x18\x27" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"


def _validator():
    spec_path = os.environ.get("THIRDS_OPENAPI_SPEC")
    if not spec_path:
        return None
    try:
        import jsonschema
    except ImportError:
        return None
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    root = {"$id": "https://spec.local/", "components": spec["components"]}
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    registry = Registry().with_resource("https://spec.local/", Resource.from_contents(root, default_specification=DRAFT202012))

    def validate(name, body):
        schema = {"$ref": f"https://spec.local/#/components/schemas/{name}"}
        v = jsonschema.Draft202012Validator(schema, registry=registry)
        errors = [f"{'/'.join(map(str, e.absolute_path))} {e.message[:160]}" for e in v.iter_errors(body)]
        return errors[:3]
    return validate


class MockAPI:
    def __init__(self):
        self.requests = []
        self.bodies = []
        self.jobs = {}
        self.downloads = {}
        self.idem = {}
        self.validate = _validator()
        self.schema_checked = 0
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, body, ctype="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _handle(self, method):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                auth = self.headers.get("Authorization", "")
                path = self.path.split("?")[0]
                entry = {"method": method, "path": path if not path.startswith("/v1/downloads/") else "/v1/downloads/<signed>",
                         "auth": "ok" if auth == f"Bearer {MOCK_KEY}" else ("other" if auth else "none"),
                         "idempotency_key": self.headers.get("Idempotency-Key"),
                         "user_agent": self.headers.get("User-Agent")}
                api.requests.append(entry)
                if path.startswith("/v1/downloads/"):
                    d = api.downloads.get(path.rsplit("/", 1)[-1])
                    return self._send(200, d[0], d[1]) if d else self._send(404, {"error": {"code": "not_found"}})
                if entry["auth"] != "ok":
                    return self._send(401, {"error": {"code": "unauthorized", "message": "Invalid API key"}})
                parts = path.strip("/").split("/")
                if len(parts) < 2 or parts[0] != "v1" or parts[1] not in ("pdf", "image"):
                    return self._send(404, {"error": {"code": "not_found", "message": "no route"}})
                kind = parts[1]
                if method == "POST" and len(parts) == 2:
                    body = json.loads(raw or b"{}")
                    api.bodies.append({"kind": kind, "body": body})
                    if api.validate:
                        errs = api.validate("PdfRequest" if kind == "pdf" else "ImageRequest", body)
                        api.schema_checked += 1
                        if errs:
                            entry["schema"] = errs
                            return self._send(400, {"error": {"code": "invalid_request", "message": "; ".join(errs)}})
                    if body.get("template_id") == "tpl_" + "0" * 32:
                        return self._send(404, {"error": {"code": "template_not_found", "message": "The template or version does not exist."}})
                    key = self.headers.get("Idempotency-Key")
                    if key in api.idem:
                        return self._send(200, api.view(api.idem[key]))
                    jid = f"{kind}_{secrets.token_hex(16)}"
                    if kind == "pdf":
                        file = (PDF, "application/pdf")
                    else:
                        img = body.get("image", {})
                        file = (png_bytes(img.get("width", 1280), img.get("height", 720)), f"image/{img.get('format', 'png')}")
                    api.jobs[jid] = {"file": file, "fail": "MOCKFAIL" in json.dumps(body.get("data", {})),
                                     "slow": body.get("reference") == "MOCKSLOW",
                                     "public": {"id": jid, "status": "queued", "credit": "reserved",
                                                "reference": body.get("reference"), "template": None,
                                                "artifact": None, "error": None, "download": None}}
                    if key:
                        api.idem[key] = jid
                    return self._send(202, api.view(jid))
                if method == "GET" and len(parts) == 3:
                    job = api.jobs.get(parts[2])
                    if not job:
                        return self._send(404, {"error": {"code": "not_found"}})
                    pub = job["public"]
                    if job["slow"]:
                        pub["status"] = "running"
                    elif job["fail"]:
                        pub.update(status="failed", credit="released", error={"category": "renderer_failure", "code": "render_failed"})
                    else:
                        pub.update(status="succeeded", credit="settled")
                    return self._send(200, api.view(parts[2]))
                return self._send(405, {"error": {"code": "method_not_allowed"}})

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def view(self, jid):
        job = self.jobs[jid]
        out = dict(job["public"])
        if out["status"] == "succeeded":
            token = secrets.token_hex(12)
            self.downloads[token] = job["file"]
            out["download"] = {"url": f"/v1/downloads/{token}", "expires_at": "2026-11-02T00:15:00Z"}
        return out

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
