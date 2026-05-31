from base64 import b64decode, b64encode, urlsafe_b64decode
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
import threading
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse
from urllib.request import Request, urlopen

import yaml


ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "raw"
RAW_FILE = RAW_DIR / "subscription.txt"

# 可通过环境变量覆盖监听地址与端口
HOST = os.environ.get("SUBUI_HOST", "127.0.0.1")
PORT = int(os.environ.get("SUBUI_PORT", "25501"))
DEFAULT_BACKEND = os.environ.get("SUBUI_BACKEND", "http://127.0.0.1:25500")
PUBLIC_BASE = f"http://{HOST}:{PORT}"

# 仅允许这些 Host 头访问，防止本机其它网页 / DNS rebinding 偷读订阅
ALLOWED_HOSTS = {
    f"127.0.0.1:{PORT}",
    f"localhost:{PORT}",
    f"[::1]:{PORT}",
}

# raw 订阅文件是全局单文件，写入加锁避免并发覆盖竞态
RAW_LOCK = threading.Lock()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("subconverter-ui")


def safe_int(value, default=0):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.info("%s - %s", self.address_string(), fmt % args)

    def host_allowed(self):
        host = (self.headers.get("Host") or "").strip().lower()
        return host in ALLOWED_HOSTS

    def reject_forbidden(self):
        """非本机 Host 头直接拒绝，挡住跨站 / rebinding 读取。"""
        if self.host_allowed():
            return False
        self.send_response(403)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("forbidden host".encode("utf-8"))
        return True

    def translate_path(self, path):
        parsed = urlparse(path)
        clean = parsed.path.lstrip("/") or "index.html"
        target = (ROOT / clean).resolve()
        # 防止 ../ 逃逸出 ROOT 造成任意文件读取
        if target != ROOT and ROOT not in target.parents:
            return str(ROOT / "index.html")
        return str(target)

    def do_GET(self):
        if self.reject_forbidden():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/check":
            self.check_backend(parsed.query)
            return
        if parsed.path == "/api/mihomo":
            self.render_mihomo()
            return
        if parsed.path == "/api/v2rayn":
            self.render_v2rayn()
            return
        super().do_GET()

    def do_HEAD(self):
        if self.reject_forbidden():
            return
        super().do_HEAD()

    def do_POST(self):
        if self.reject_forbidden():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/raw":
            self.save_raw_subscription()
            return
        self.send_response(404)
        self.end_headers()

    def check_backend(self, query):
        params = parse_qs(query)
        backend = params.get("backend", [DEFAULT_BACKEND])[0].rstrip("/")

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

        with RAW_LOCK:
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            RAW_FILE.write_bytes(body + b"\n")

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"{PUBLIC_BASE}/raw/subscription.txt".encode("utf-8"))

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

    def render_v2rayn(self):
        if not RAW_FILE.exists():
            self.send_response(404)
            self.end_headers()
            return

        proxies = parse_clash_proxies(RAW_FILE.read_text(encoding="utf-8", errors="ignore"))
        links = []
        for proxy in proxies:
            try:
                link = proxy_to_v2rayn(proxy)
            except Exception:
                log.warning("跳过无法转换的 Clash 节点: %s", proxy.get("name"))
                link = None
            if link:
                links.append(link)
        if not links:
            self.send_response(422)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("没有识别到可转换的 Clash 节点。".encode("utf-8"))
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(("\n".join(links) + "\n").encode("utf-8"))


def decode_subscription(text):
    text = text.strip()
    if "://" in text or "proxies:" in text:
        return text

    decoded = decode_base64_text(text)
    if "://" in decoded or "proxies:" in decoded:
        return decoded
    return text


def decode_base64_text(text):
    compact = "".join(text.split())
    if not compact:
        return ""
    padding = "=" * (-len(compact) % 4)
    for decoder in (urlsafe_b64decode, b64decode):
        try:
            decoded = decoder(compact + padding)
            return decoded.decode("utf-8", errors="ignore")
        except Exception:
            continue
    return ""


def encode_base64_text(text):
    return b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def parse_nodes(text):
    decoded = decode_subscription(text)
    proxies = []
    used_names = set()

    for line in decoded.replace("\r", "\n").split("\n"):
        line = line.strip()
        if not line or "://" not in line:
            continue

        proxy = None
        try:
            if line.startswith("vless://"):
                proxy = parse_vless(line)
            elif line.startswith("trojan://"):
                proxy = parse_trojan(line)
            elif line.startswith("vmess://"):
                proxy = parse_vmess(line)
            elif line.startswith("ss://"):
                proxy = parse_ss(line)
        except Exception:
            log.warning("跳过无法解析的节点: %.40s", line)
            proxy = None

        if proxy:
            proxy["name"] = unique_name(proxy.get("name") or proxy["server"], used_names)
            proxies.append(proxy)

    return proxies


def parse_clash_proxies(text):
    decoded = decode_subscription(text)
    try:
        data = yaml.safe_load(decoded) or {}
    except Exception:
        return []

    proxies = data.get("proxies", []) if isinstance(data, dict) else []
    if not isinstance(proxies, list):
        return []
    return [proxy for proxy in proxies if isinstance(proxy, dict)]


def proxy_to_v2rayn(proxy):
    proxy_type = str(proxy.get("type", "")).lower()
    if proxy_type == "vmess":
        return clash_vmess_to_link(proxy)
    if proxy_type == "vless":
        return clash_vless_to_link(proxy)
    if proxy_type == "trojan":
        return clash_trojan_to_link(proxy)
    if proxy_type == "ss":
        return clash_ss_to_link(proxy)
    return None


def clash_vmess_to_link(proxy):
    server = proxy.get("server")
    uuid = proxy.get("uuid")
    if not server or not uuid:
        return None

    network = str(proxy.get("network") or "tcp")
    host = ""
    path = ""
    if network == "ws":
        ws_opts = proxy.get("ws-opts") or {}
        ws_headers = ws_opts.get("headers") or {}
        host = ws_headers.get("Host") or ws_headers.get("host") or ""
        path = ws_opts.get("path") or ""
    elif network == "grpc":
        grpc_opts = proxy.get("grpc-opts") or {}
        path = grpc_opts.get("grpc-service-name") or ""
    elif network in ("h2", "http"):
        h2_opts = proxy.get("h2-opts") or proxy.get("http-opts") or {}
        hosts = h2_opts.get("host") or []
        host = (hosts[0] if hosts else "") if isinstance(hosts, list) else str(hosts)
        h2_path = h2_opts.get("path") or ""
        path = (h2_path[0] if h2_path else "") if isinstance(h2_path, list) else str(h2_path)

    sni = proxy.get("servername") or proxy.get("sni") or ""
    # 仅传输层需要伪装域名时，host 缺省回退到 sni；tcp 不写 host
    if not host and network in ("ws", "h2", "http"):
        host = sni

    data = {
        "v": "2",
        "ps": str(proxy.get("name") or server),
        "add": str(server),
        "port": str(safe_int(proxy.get("port"), 443)),
        "id": str(uuid),
        "aid": str(proxy.get("alterId") or proxy.get("alterid") or 0),
        "scy": str(proxy.get("cipher") or "auto"),
        "net": network,
        "type": "none",
        "host": str(host),
        "path": str(path),
        "tls": "tls" if proxy.get("tls") else "",
        "sni": str(sni),
        "fp": str(proxy.get("client-fingerprint") or ""),
    }
    return "vmess://" + encode_base64_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def clash_vless_to_link(proxy):
    server = proxy.get("server")
    uuid = proxy.get("uuid")
    if not server or not uuid:
        return None

    params = {
        "encryption": "none",
        "type": proxy.get("network") or "tcp",
    }
    add_tls_params(params, proxy)
    add_transport_params(params, proxy)
    if proxy.get("flow"):
        params["flow"] = proxy["flow"]
    return build_share_url("vless", uuid, server, proxy.get("port") or 443, params, proxy.get("name") or server)


def clash_trojan_to_link(proxy):
    server = proxy.get("server")
    password = proxy.get("password")
    if not server or not password:
        return None

    params = {"type": proxy.get("network") or "tcp"}
    add_tls_params(params, proxy, default_tls=True)
    add_transport_params(params, proxy)
    return build_share_url("trojan", password, server, proxy.get("port") or 443, params, proxy.get("name") or server)


def clash_ss_to_link(proxy):
    server = proxy.get("server")
    cipher = proxy.get("cipher")
    password = proxy.get("password")
    if not server or not cipher or not password:
        return None

    port = safe_int(proxy.get("port"), 443)
    # SIP002: 仅对 method:password 做 base64，host/port 明文，更稳且能携带插件
    userinfo = encode_base64_text(f"{cipher}:{password}")
    plugin = build_ss_plugin(proxy)
    query = f"?plugin={quote(plugin, safe='')}" if plugin else ""
    name = quote(str(proxy.get("name") or server), safe="")
    return f"ss://{userinfo}@{server}:{port}{query}#{name}"


def build_ss_plugin(proxy):
    plugin = str(proxy.get("plugin") or "").strip()
    if not plugin:
        return ""
    opts = proxy.get("plugin-opts") or {}

    if plugin in ("obfs", "simple-obfs"):
        parts = ["obfs-local"]
        if opts.get("mode"):
            parts.append(f"obfs={opts['mode']}")
        if opts.get("host"):
            parts.append(f"obfs-host={opts['host']}")
        return ";".join(parts)

    if plugin == "v2ray-plugin":
        parts = ["v2ray-plugin"]
        if opts.get("mode"):
            parts.append(f"mode={opts['mode']}")
        if opts.get("tls"):
            parts.append("tls")
        if opts.get("host"):
            parts.append(f"host={opts['host']}")
        if opts.get("path"):
            parts.append(f"path={opts['path']}")
        return ";".join(parts)

    # 未知插件不臆造参数，避免生成错误链接
    return ""


def add_tls_params(params, proxy, default_tls=False):
    if proxy.get("reality-opts"):
        params["security"] = "reality"
        reality = proxy.get("reality-opts") or {}
        if reality.get("public-key"):
            params["pbk"] = reality["public-key"]
        if reality.get("short-id"):
            params["sid"] = reality["short-id"]
    elif proxy.get("tls") or default_tls:
        params["security"] = "tls"
    else:
        params["security"] = "none"

    servername = proxy.get("servername") or proxy.get("sni")
    if servername:
        params["sni"] = servername
    if proxy.get("client-fingerprint"):
        params["fp"] = proxy["client-fingerprint"]
    if proxy.get("skip-cert-verify"):
        params["allowInsecure"] = "1"


def add_transport_params(params, proxy):
    network = str(proxy.get("network") or "tcp")
    if network == "ws":
        ws_opts = proxy.get("ws-opts") or {}
        headers = ws_opts.get("headers") or {}
        if ws_opts.get("path"):
            params["path"] = ws_opts["path"]
        host = headers.get("Host") or headers.get("host")
        if host:
            params["host"] = host
    elif network == "grpc":
        grpc_opts = proxy.get("grpc-opts") or {}
        service = grpc_opts.get("grpc-service-name")
        if service:
            params["serviceName"] = service


def build_share_url(scheme, userinfo, server, port, params, name):
    query = urlencode({key: value for key, value in params.items() if value})
    fragment = quote(str(name), safe="")
    return f"{scheme}://{quote(str(userinfo), safe='')}@{server}:{safe_int(port, 443)}?{query}#{fragment}"


def unique_name(name, used):
    base = unquote(name).strip() or "节点"
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
        "uuid": unquote(parsed.username) if parsed.username else None,
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
        "password": unquote(parsed.username) if parsed.username else None,
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
        "port": safe_int(data.get("port"), 443),
        "uuid": data.get("id"),
        "alterId": safe_int(data.get("aid"), 0),
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
    name = parsed.fragment or "SS"
    payload = line.removeprefix("ss://").split("#", 1)[0].split("?", 1)[0]
    userinfo = ""
    server = parsed.hostname
    port = parsed.port

    if "@" in payload:
        userinfo, host = payload.rsplit("@", 1)
        server, port = parse_host_port(host)
    else:
        decoded = decode_base64_text(payload)
        if "@" in decoded:
            userinfo, host = decoded.rsplit("@", 1)
            server, port = parse_host_port(host)

    decoded_userinfo = decode_base64_text(userinfo or "") or unquote(userinfo or "")
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

    # 还原 SIP002 插件参数，避免导入带 obfs / v2ray-plugin 的 SS 链接后丢失插件
    plugin_name, plugin_opts = parse_ss_plugin(extract_query_value(parsed.query, "plugin"))
    if plugin_name:
        proxy["plugin"] = plugin_name
        if plugin_opts:
            proxy["plugin-opts"] = plugin_opts

    return proxy if proxy["server"] and proxy["port"] and method and password else None


def extract_query_value(raw_query, key):
    # 手动按 & 切分, 不依赖 parse_qs 对 ; 的版本相关处理
    prefix = key + "="
    for part in (raw_query or "").split("&"):
        if part.startswith(prefix):
            return unquote(part[len(prefix):])
    return ""


def parse_ss_plugin(plugin_str):
    plugin_str = (plugin_str or "").strip()
    if not plugin_str:
        return None, None

    segments = [seg for seg in plugin_str.split(";") if seg]
    if not segments:
        return None, None

    plugin = segments[0]
    opts = {}
    for seg in segments[1:]:
        key, sep, value = seg.partition("=")
        opts[key] = value if sep else True  # 无值项视为开关, 如 tls

    if plugin in ("obfs-local", "simple-obfs", "obfs"):
        clash_opts = {}
        if opts.get("obfs"):
            clash_opts["mode"] = opts["obfs"]
        if opts.get("obfs-host"):
            clash_opts["host"] = opts["obfs-host"]
        return "obfs", clash_opts

    if plugin == "v2ray-plugin":
        clash_opts = {}
        if opts.get("mode"):
            clash_opts["mode"] = opts["mode"]
        if "tls" in opts:
            clash_opts["tls"] = True
        if opts.get("host"):
            clash_opts["host"] = opts["host"]
        if opts.get("path"):
            clash_opts["path"] = opts["path"]
        return "v2ray-plugin", clash_opts

    return None, None


def parse_host_port(host):
    host = unquote(host).strip()
    if host.startswith("[") and "]:" in host:
        server, _, port_text = host[1:].partition("]:")
    else:
        server, _, port_text = host.rpartition(":")
    try:
        port = int(port_text or 0)
    except ValueError:
        port = 0
    return server, port


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
    config = {
        "mixed-port": 7890,
        "allow-lan": True,
        "mode": "rule",
        "log-level": "info",
        "external-controller": "127.0.0.1:9090",
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "节点选择",
                "type": "select",
                "proxies": ["自动选择", "DIRECT", *names],
            },
            {
                "name": "自动选择",
                "type": "url-test",
                "url": "http://www.gstatic.com/generate_204",
                "interval": 300,
                "proxies": names,
            },
        ],
        "rules": [
            "GEOIP,CN,DIRECT",
            "MATCH,节点选择",
        ],
    }
    # allow_unicode 保留中文节点名；sort_keys=False 保持字段顺序可读
    return yaml.safe_dump(config, allow_unicode=True, sort_keys=False, default_flow_style=False)


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    log.info("本地订阅转换网页界面已启动: %s/", PUBLIC_BASE)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("正在关闭...")
        server.shutdown()
