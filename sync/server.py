"""
局域网共享记忆同步服务
每台设备跑一个，监听 8520 端口
"""
import sys
import json
import socket
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from memory.store import all_memories, remember
from memory.error_archive import check_before

PORT = 8520


def get_local_ip() -> str:
    """拿本机局域网 IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class SyncHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # 静默，不打日志到控制台
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/ping":
            self._send_json({"ok": True, "ip": get_local_ip(), "port": PORT})
            return

        if path == "/memory":
            agent_id = qs.get("agent", ["default"])[0]
            self._send_json({"agent": agent_id, "memories": all_memories(agent_id)})
            return

        if path == "/errors":
            scenario = qs.get("scenario", [""])[0]
            self._send_json({"errors": check_before(scenario)})
            return

        self._send_json({"error": "unknown path"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/memory":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                data = json.loads(body)
                agent_id = data["agent"]
                for k, v in data.get("memories", {}).items():
                    remember(agent_id, k, v)
                self._send_json({"ok": True, "synced": len(data.get("memories", {}))})
            except Exception as e:
                self._send_json({"error": str(e)}, 400)
            return

        self._send_json({"error": "unknown path"}, 404)


def start_server():
    ip = get_local_ip()
    server = HTTPServer(("0.0.0.0", PORT), SyncHandler)
    print(f"[同步服务] 本机 IP: {ip}  监听端口: {PORT}")
    print(f"[同步服务] 其他设备访问: http://{ip}:{PORT}/ping")
    print(f"[同步服务] 按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[同步服务] 已停止")
        server.shutdown()


if __name__ == "__main__":
    start_server()