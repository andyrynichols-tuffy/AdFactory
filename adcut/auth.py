"""Password login for using the editor from the web (through the Cloudflare tunnel).

On this PC (a request straight to 127.0.0.1, not through the tunnel) there's no login.
Anything that came through the tunnel needs the password once per browser; it's kept as a
signed cookie for 30 days. The password lives hashed in AD_DATA/auth.json; a copy for you
to hand out is in AD_DATA/login.txt (this PC only, not OneDrive)."""
import hashlib
import hmac
import json
import secrets
import time

from . import store

AUTH = store.AD_DATA / "auth.json"
NOTE = store.AD_DATA / "login.txt"
COOKIE = "af_session"
DAYS = 30
WORDS = ("maple river tiger canvas pepper orbit velvet harbor cactus lantern meadow rocket "
         "falcon cobalt willow ember pixel summit marble comet").split()
_fails = {}  # ip -> [times]


def _hash(pw: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()


def _load() -> dict:
    if AUTH.exists():
        return json.loads(AUTH.read_text(encoding="utf-8"))
    return set_password(None)


def set_password(pw: str = None) -> dict:
    """Set (or make up) the web password; returns the auth record."""
    if not pw:
        pw = "-".join(secrets.choice(WORDS) for _ in range(3)) + "-" + str(secrets.randbelow(90) + 10)
    salt = secrets.token_hex(16)
    rec = {"salt": salt, "hash": _hash(pw, salt), "secret": secrets.token_hex(32), "set": time.time()}
    store.AD_DATA.mkdir(parents=True, exist_ok=True)
    AUTH.write_text(json.dumps(rec), encoding="utf-8")
    NOTE.write_text("Ad Factory web password (give this to whoever uses the web link):\n\n"
                    f"    {pw}\n\nChange it: .venv\\Scripts\\python.exe -m adcut password \"new password\"\n",
                    encoding="utf-8")
    return rec


def remote(request) -> bool:
    """Came through the tunnel (or anything else that isn't this PC talking to itself)."""
    h = request.headers
    if h.get("cf-connecting-ip") or h.get("x-forwarded-for") or h.get("cf-ray"):
        return True
    return (request.client.host if request.client else "") not in ("127.0.0.1", "::1", "localhost")


def _sign(secret: str, exp: int) -> str:
    return f"{exp}.{hmac.new(bytes.fromhex(secret), str(exp).encode(), hashlib.sha256).hexdigest()}"


def signed_in(request) -> bool:
    v = request.cookies.get(COOKIE, "")
    try:
        exp = int(v.split(".")[0])
    except ValueError:
        return False
    return exp > time.time() and hmac.compare_digest(v, _sign(_load()["secret"], exp))


def ip_of(request) -> str:
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")


def try_login(request, pw: str):
    """The cookie value on the right password, else None (5 wrong tries = 10 min wait)."""
    ip, now = ip_of(request), time.time()
    recent = [t for t in _fails.get(ip, []) if now - t < 600]
    if len(recent) >= 5:
        return "wait"
    rec = _load()
    if hmac.compare_digest(_hash(pw or "", rec["salt"]), rec["hash"]):
        _fails.pop(ip, None)
        return _sign(rec["secret"], int(now + DAYS * 86400))
    _fails[ip] = recent + [now]
    return None


LOGIN_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ad Factory · sign in</title><style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0f0f12;color:#eee;font:15px system-ui,sans-serif}
form{background:#1b1b21;padding:28px;border-radius:14px;width:min(340px,86vw);box-shadow:0 10px 40px #0008}
h1{font-size:20px;margin:0 0 4px}p{color:#999;margin:0 0 18px;font-size:13px}
input{width:100%;box-sizing:border-box;padding:11px 12px;border-radius:9px;border:1px solid #333;background:#111;color:#eee;font-size:15px}
button{margin-top:12px;width:100%;padding:11px;border:0;border-radius:9px;background:#FE2C55;color:#fff;font-weight:700;font-size:15px;cursor:pointer}
.err{color:#FE2C55;font-size:13px;margin-top:10px}</style></head><body>
<form method="post" action="/login"><h1>🎬 Ad Factory</h1><p>Enter the password to open the editor.</p>
<input type="password" name="password" autofocus autocomplete="current-password" placeholder="Password">
<button>Open editor</button>{err}</form></body></html>"""
LOGIN_PT = {"Enter the password to open the editor.": "Digite a senha para abrir o editor.",
            'placeholder="Password"': 'placeholder="Senha"', "<button>Open editor</button>": "<button>Abrir o editor</button>",
            "Ad Factory · sign in": "Ad Factory · entrar", '<html>': '<html lang="pt-BR">',
            "Wrong password.": "Senha errada.", "Too many tries. Wait 10 minutes.": "Tentativas demais. Espere 10 minutos."}


def login_html(request, err="") -> str:
    """The sign-in page, in Portuguese for a browser set to Portuguese."""
    html = LOGIN_HTML.replace("{err}", err)
    if (request.headers.get("accept-language") or "").lower().startswith("pt"):
        for a, b in LOGIN_PT.items():
            html = html.replace(a, b)
    return html
