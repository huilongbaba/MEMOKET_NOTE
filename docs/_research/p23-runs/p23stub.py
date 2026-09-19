"""P23 #3 / #4 截图用的假模型端点（零真模型调用，不连外网）。

  端口 A（argv[1]）= 带视觉的那台：收到带 image_url 的请求就回「738」
  端口 B（argv[1]+1）= 纯文字那台：照样 200，但回一句没用的话（模型不看图时就是这样）

两台都实现 GET /v1/models，好拍「测一下之后一键填模型名」那一排芯片。
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELS = {"object": "list", "data": [{"id": "qwen3:8b"}, {"id": "qwen2.5vl:7b"}, {"id": "llama3.2"}]}


def handler(sees_images: bool):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, payload):
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            p = self.path.rstrip("/")
            if p.endswith("/models"):
                self._send(200, MODELS)
            elif p.endswith("/health"):
                self._send(200, {"status": "ok"})
            else:
                self._send(404, {"error": "no"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n)
            # 学新一代 OpenAI 模型那一手：带 max_tokens 就回 400（P23 #4 实拍抓到的那条）
            if b'"max_tokens"' in raw:
                self._send(400, {"error": {"message": "Unsupported parameter: 'max_tokens' is not "
                                                      "supported with this model. Use "
                                                      "'max_completion_tokens' instead."}})
                return
            has_img = b"image_url" in raw
            if has_img and sees_images:
                text = "738"
            elif has_img:
                text = "这是一张图片。"
            else:
                text = "ok"
            self._send(200, {"choices": [{"message": {"content": text}}], "usage": {}})

        def log_message(self, *a):
            pass
    return H


def hang_handler():
    """收下请求就不回——「模型收下请求不回」那一列（临界条件表的「超时」）。"""
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(n)
            import time
            time.sleep(600)

        def do_GET(self):
            import time
            time.sleep(600)

        def log_message(self, *a):
            pass
    return H


if __name__ == "__main__":
    a = int(sys.argv[1])
    threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", a), handler(True)).serve_forever,
                     daemon=True).start()
    threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", a + 2), hang_handler()).serve_forever,
                     daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", a + 1), handler(False)).serve_forever()
