from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from grapher import convert_ggb_to_asy

MAX_BYTES = 4 * 1024 * 1024

class handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self.send_json(400, {"error": "没有收到文件。"})
            return
        if length > MAX_BYTES:
            self.send_json(413, {"error": "文件不能超过 4 MB。"})
            return
        query = parse_qs(urlparse(self.path).query)
        preserve_style = query.get("preserve_style", ["false"])[0].lower() == "true"
        debug = query.get("debug", ["false"])[0].lower() == "true"
        path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".ggb", delete=False) as temp:
                temp.write(self.rfile.read(length))
                path = Path(temp.name)
            result = convert_ggb_to_asy(path, preserve_style=preserve_style, debug=debug)
            self.send_json(200, {"code": result.code, "warnings": result.warnings, "object_count": len(result.objects)})
        except (OSError, ValueError) as error:
            self.send_json(422, {"error": str(error)})
        except Exception:
            self.send_json(500, {"error": "转换失败，请检查文件是否有效。"})
        finally:
            if path is not None:
                path.unlink(missing_ok=True)
