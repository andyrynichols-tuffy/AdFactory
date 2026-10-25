"""The few AI features (all marked ✨ AI in the app): one prompt to the Claude Code CLI
(`claude -p`, the signed-in subscription; no API key), answer back as text or JSON. Runs in
its own empty folder so it doesn't wander the repo. Everything else in the app is local."""
import json
import re
import subprocess
import time

from supercut import asks

from . import store

AI_DIR = store.AD_DATA / "ai"
SIGN_IN = ("✨ AI needs Claude Code signed in on this PC, once: open a terminal, type claude, "
           "then /login and follow the steps")
_st = {"t": 0.0, "v": None}


def status(fresh=False) -> dict:
    """{installed, signed_in}: rechecked every 5 min once signed in, every 30 s until then (it starts the CLI)."""
    ttl = 300 if (_st["v"] or {}).get("signed_in") else 30
    if fresh or _st["v"] is None or time.time() - _st["t"] > ttl:
        _st.update(t=time.time(), v=asks.status())
    return _st["v"]


def available() -> bool:
    st = status()
    return bool(st["installed"] and st["signed_in"])


def ask(prompt: str, cwd=None, tools=(), timeout=300) -> str:
    exe = asks.claude_exe()
    if not exe:
        raise RuntimeError("Claude Code isn't installed on this PC, so the ✨ AI buttons can't run")
    if not status()["signed_in"]:
        raise RuntimeError(SIGN_IN)
    AI_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [exe, "-p", "--output-format", "text"]
    if tools:
        cmd += ["--allowedTools", *tools]
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, cwd=str(cwd or AI_DIR), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = (p.stdout or "").strip()
    if p.returncode or not out:
        msg = (p.stderr or out or "no answer").strip().splitlines()
        raise RuntimeError("Claude didn't answer: " + (msg[-1][:200] if msg else "no answer"))
    return out


def ask_json(prompt: str, **kw):
    """The first JSON object/array in the answer."""
    out = ask(prompt + "\n\nAnswer with only the JSON, no other text.", **kw)
    m = re.search(r"```(?:json)?\s*(.*?)```", out, re.S)
    body = m.group(1) if m else out
    start = min([i for i in (body.find("{"), body.find("[")) if i >= 0] or [0])
    return json.loads(body[start:body.rfind("}" if body[start] == "{" else "]") + 1])
