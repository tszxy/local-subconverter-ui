from base64 import b64decode, b64encode
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "raw"
RAW_FILE = RAW_DIR / "subscription.txt"


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        parsed = urlparse(path)
        clean = parsed.path.lstrip("/") or "index.html"
        return str((ROOT / clean).resolve())

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/check":
            self.check_backend(parsed.query)
            return
        if parsed.path == "/api/mihomo":
            self.render_mihomo()
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/raw":
            self.save_raw_subscription()
            return
        self.send_response(404)
        self.end_headers()

    def check_backend(self, query):
        params = parse_qs(query)
        backend = params.get("backend", ["http://127.0.0.1:25500"])[0].rstrip("/")

        if not backend.startswith(("http://127.0.0.1:", "http://localhost:")):
            self.send_response(400)
            self.end_headers()
            return

        try:
            request = Request(f"{backend}/version", headers={"User-Agent": "subconverter-ui"})
            with urlopen(request, timeout=2) as response:
                ok = response.status == 200
        except Exception:
            ok = False

        self.send_response(200 if ok else 503)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok" if ok else b"unavailable")

    def save_raw_subscription(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0

        if size <= 0 or size > 1024 * 1024:
            self.send_response(400)
            self.end_headers()
            return

        body = self.rfile.read(size).strip()
        text = body.decode("utf-8", errors="ignore")
        if "://" in text:
            body = b64encode(body)

        RAW_DIR.mkdir(parents=True, exist_ok=True)
        RAW_FILE.write_bytes(body + b"\n")

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"http://127.0.0.1:25501/raw/subscription.txt")

    def render_mihomo(self):
        if not RAW_FILE.exists():
            self.send_response(404)
            self.end_headers()
            return

        proxies = parse_nodes(RAW_FILE.read_text(encoding="utf-8", errors="ignore"))
        if not proxies:
            self.send_response(422)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("没有识别到可转换节点。".encode("utf-8"))
            return

        config = build_mihomo_config(proxies)
        self.send_response(200)
        self.send_header("Content-Type", "text/yaml; charset=utf-8")
        self.end_headers()
        self.wfile.write(config.encode("utf-8"))


def decode_subscription(text):
    text = text.strip()
    if "://" in text:
        return text

    compact = "".join(text.split())
    padding = "=" * (-len(compact) % 4)
    try:
        decoded = b64decode(compact + padding, validate=False)
        return decoded.decode("utf-8", errors="ignore")
    except Exception:
        return text


def parse_nodes(text):
    decoded = decode_subscription(text)
    proxies = []
    used_names = set()

    for line in decoded.replace("\r", "\n").split("\n"):
        line = line.strip()
        if not line or "://" not in line:
            continue

        proxy = None
        if line.startswith("vless://"):
            proxy = parse_vless(line)
        elif line.startswith("trojan://"):
            proxy = parse_trojan(line)
        elif line.startswith("vmess://"):
            proxy = parse_vmess(line)
        elif line.startswith("ss://"):
            proxy = parse_ss(line)

        if proxy:
            proxy["name"] = unique_name(proxy.get("name") or proxy["server"], used_names)
            proxies.append(proxy)

    return proxies


def unique_name(name, used):
    base = yaml_scalar(unquote(name).strip() or "节点", quote=False)
    name = base
    index = 2
    while name in used:
        name = f"{base} {index}"
        index += 1
    used.add(name)
    return name


def parse_vless(line):
    parsed = urlparse(line)
    query = parse_qs(parsed.query)
    security = first(query, "security")
    network = first(query, "type") or first(query, "net")
    proxy = {
        "name": parsed.fragment or parsed.hostname or "VLESS",
        "type": "vless",
        "server": parsed.hostname,
        "port": parsed.port or 443,
        "uuid": parsed.username,
        "udp": True,
        "tls": security in ("tls", "reality"),
    }
    add_common_tls(proxy, query, security)
    add_network(proxy, query, network)
    flow = first(query, "flow")
    if flow:
        proxy["flow"] = flow
    return proxy if proxy["server"] and proxy["uuid"] else None


def parse_trojan(line):
    parsed = urlparse(line)
    query = parse_qs(parsed.query)
    security = first(query, "security") or "tls"
    network = first(query, "type") or first(query, "net")
    proxy = {
        "name": parsed.fragment or parsed.hostname or "Trojan",
        "type": "trojan",
        "server": parsed.hostname,
        "port": parsed.port or 443,
        "password": parsed.username,
        "udp": True,
        "tls": security in ("tls", "reality"),
    }
    add_common_tls(proxy, query, security)
    add_network(proxy, query, network)
    return proxy if proxy["server"] and proxy["password"] else None


def parse_vmess(line):
    payload = line.removeprefix("vmess://").strip()
    padding = "=" * (-len(payload) % 4)
    try:
        data = json.loads(b64decode(payload + padding).decode("utf-8", errors="ignore"))
    except Exception:
        return None

    proxy = {
        "name": data.get("ps") or data.get("add") or "VMess",
        "type": "vmess",
        "server": data.get("add"),
        "port": int(data.get("port") or 443),
        "uuid": data.get("id"),
        "alterId": int(data.get("aid") or 0),
        "cipher": data.get("scy") or "auto",
        "udp": True,
        "tls": str(data.get("tls", "")).lower() == "tls",
    }

    query = {
        "host": [data.get("host", "")],
        "path": [data.get("path", "")],
        "sni": [data.get("sni", "")],
        "fp": [data.get("fp", "")],
    }
    add_common_tls(proxy, query, "tls" if proxy["tls"] else "")
    add_network(proxy, query, data.get("net"))
    return proxy if proxy["server"] and proxy["uuid"] else None


def parse_ss(line):
    parsed = urlparse(line)
    name = parsed.fragment or parsed.hostname or "SS"
    userinfo = parsed.netloc.rsplit("@", 1)[0] if "@" in parsed.netloc else parsed.username
    server = parsed.hostname
    port = parsed.port

    if "@" not in parsed.netloc:
        decoded = decode_subscription(userinfo or "")
        if "@" in decoded:
            userinfo, host = decoded.rsplit("@", 1)
            server, _, port_text = host.rpartition(":")
            port = int(port_text or 0)

    decoded_userinfo = decode_subscription(userinfo or "")
    if ":" not in decoded_userinfo:
        decoded_userinfo = unquote(userinfo or "")
    method, _, password = decoded_userinfo.partition(":")

    proxy = {
        "name": name,
        "type": "ss",
        "server": server,
        "port": port,
        "cipher": method,
        "password": password,
        "udp": True,
    }
    return proxy if proxy["server"] and proxy["port"] and method and password else None


def first(query, key):
    value = query.get(key, [""])[0]
    return unquote(value) if value else ""


def add_common_tls(proxy, query, security):
    servername = first(query, "sni") or first(query, "peer") or first(query, "host")
    fingerprint = first(query, "fp")
    if servername:
        proxy["servername"] = servername
    if fingerprint:
        proxy["client-fingerprint"] = fingerprint
    if security == "reality":
        proxy["reality-opts"] = {
            "public-key": first(query, "pbk") or first(query, "public-key"),
            "short-id": first(query, "sid") or first(query, "short-id"),
        }


def add_network(proxy, query, network):
    if not network or network == "tcp":
        return
    proxy["network"] = network
    if network == "ws":
        host = first(query, "host")
        path = first(query, "path") or "/"
        proxy["ws-opts"] = {"path": path}
        if host:
            proxy["ws-opts"]["headers"] = {"Host": host}
    elif network == "grpc":
        service = first(query, "serviceName") or first(query, "service")
        if service:
            proxy["grpc-opts"] = {"grpc-service-name": service}


def build_mihomo_config(proxies):
    names = [proxy["name"] for proxy in proxies]
    lines = [
        "mixed-port: 7890",
        "allow-lan: true",
        "mode: rule",
        "log-level: info",
        "external-controller: 127.0.0.1:9090",
        "proxies:",
    ]

    for proxy in proxies:
        lines.extend(render_proxy(proxy))

    lines.extend([
        "proxy-groups:",
        "  - name: 节点选择",
        "    type: select",
        "    proxies:",
        "      - 自动选择",
        "      - DIRECT",
    ])
    lines.extend([f"      - {yaml_scalar(name)}" for name in names])
    lines.extend([
        "  - name: 自动选择",
        "    type: url-test",
        "    url: http://www.gstatic.com/generate_204",
        "    interval: 300",
        "    proxies:",
    ])
    lines.extend([f"      - {yaml_scalar(name)}" for name in names])
    lines.extend([
        "rules:",
        "  - GEOIP,CN,DIRECT",
        "  - MATCH,节点选择",
        "",
    ])
    return "\n".join(lines)


def render_proxy(proxy):
    lines = ["  - " + render_kv("name", proxy["name"])]
    for key, value in proxy.items():
        if key == "name":
            continue
        lines.append(f"    {key}: {render_value(value)}")
    return lines


def render_kv(key, value):
    return f"{key}: {render_value(value)}"


def render_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, dict):
        inner = ", ".join(f"{k}: {render_value(v)}" for k, v in value.items() if v)
        return "{" + inner + "}"
    return yaml_scalar(str(value))


def yaml_scalar(value, quote=True):
    value = value.strip()
    if not quote and value:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 25501), Handler)
    server.serve_forever()
