"""The few AI features (all marked ✨ AI in the app): one prompt to the Claude Code CLI
(`claude -p`, the signed-in subscription; no API key), answer back as text or JSON. Runs in
its own empty folder so it doesn't wander the repo. Everything else in the app is local."""
import json
import re
import subprocess

from supercut import asks

from . import store

AI_DIR = store.AD_DATA / "ai"


def available() -> bool:
    return bool(asks.claude_exe())


def ask(prompt: str, cwd=None, tools=(), timeout=300) -> str:
    exe = asks.claude_exe()
    if not exe:
        raise RuntimeError("Claude Code isn't installed on this PC, so the ✨ AI buttons can't run")
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
