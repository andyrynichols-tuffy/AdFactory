"""Comedy sound effects, synthesized with ffmpeg (no samples, nothing to license).

Each entry is a lavfi audio graph. Generated once into DATA_DIR/sfx/<name>.wav."""
import subprocess
from pathlib import Path

from .config import DATA_DIR, FFMPEG

SR = 48000


def _ev(expr: str, d: float, post: str = "") -> str:
    return f"aevalsrc='{expr}':s={SR}:d={d}" + (f",{post}" if post else "")


LIBRARY = {
    # cut transitions
    "whoosh": ("anoisesrc=d=0.38:c=pink:r=48000:a=0.7,highpass=f=500,lowpass=f=7000,"
               "afade=t=in:d=0.17:curve=exp,afade=t=out:st=0.17:d=0.21"),
    "pop": _ev("0.8*sin(2*PI*(950-1600*t)*t)*exp(-28*t)", 0.16),
    # punchline hits
    "boom": _ev("0.95*sin(2*PI*(45*t+7.5*(1-exp(-8*t))))*exp(-3*t)", 1.6,
                "lowpass=f=900,volume=2.2,alimiter=limit=0.95"),
    "ding": _ev("0.4*(sin(2*PI*1568*t)+0.5*sin(2*PI*3136*t)+0.25*sin(2*PI*4704*t))*exp(-4*t)", 1.3),
    "cash": _ev("if(lt(t,0.07),(random(0)*2-1)*0.55*exp(-25*t),0)"
                "+if(gte(t,0.09),0.35*(sin(2*PI*2093*(t-0.09))+0.6*sin(2*PI*2637*(t-0.09))"
                "+0.4*sin(2*PI*3136*(t-0.09)))*exp(-5*(t-0.09)),0)", 1.1),
    "buzzer": _ev("0.3*((gt(sin(2*PI*98*t),0)*2-1)+(gt(sin(2*PI*104*t),0)*2-1))"
                  "*if(lt(t,0.6),1,exp(-30*(t-0.6)))", 0.75, "lowpass=f=2500"),
    "boing": _ev("0.6*sin(2*PI*(260*t-(120/(2*PI*11))*exp(-2.5*t)*cos(2*PI*11*t)))*exp(-2.2*t)", 1.1),
    "gavel": _ev("0.8*(sin(2*PI*700*t)*exp(-60*t)+if(gte(t,0.22),sin(2*PI*640*(t-0.22))*exp(-60*(t-0.22)),0))"
                 "+0.3*(random(0)*2-1)*(exp(-90*t)+if(gte(t,0.22),exp(-90*(t-0.22)),0))", 0.6,
                 "lowpass=f=3000"),
    # reactions
    "scratch": _ev("0.55*sin(2*PI*240*t-(230/7)*cos(2*PI*7*t))*(0.65+0.35*random(0))"
                   "*if(lt(t,0.4),1,exp(-25*(t-0.4)))", 0.55, "bandpass=f=1100:width_type=o:w=2.5,volume=2"),
    "crickets": _ev("0.22*sin(2*PI*4600*t)*lt(mod(t,0.95),0.2)*lt(mod(mod(t,0.95),0.065),0.035)"
                    "+0.16*sin(2*PI*5150*t)*lt(mod(t+0.45,1.1),0.2)*lt(mod(mod(t+0.45,1.1),0.065),0.035)", 2.8),
    "sad_trombone": _ev(
        "0.32*if(lt(t,0.42),(sin(2*PI*293.7*t)+0.5*sin(4*PI*293.7*t)+0.3*sin(6*PI*293.7*t))*min(1,t*30),"
        "if(lt(t,0.84),(sin(2*PI*277.2*(t-0.42))+0.5*sin(4*PI*277.2*(t-0.42))+0.3*sin(6*PI*277.2*(t-0.42))),"
        "if(lt(t,1.26),(sin(2*PI*261.6*(t-0.84))+0.5*sin(4*PI*261.6*(t-0.84))+0.3*sin(6*PI*261.6*(t-0.84))),"
        "(sin(2*PI*246.9*(t-1.26)+0.35*sin(2*PI*6*(t-1.26)))+0.5*sin(4*PI*246.9*(t-1.26))"
        "+0.3*sin(6*PI*246.9*(t-1.26)))*exp(-1.4*(t-1.26)))))", 2.6, "lowpass=f=2200"),
    "rimshot": ("aevalsrc='0.8*(sin(2*PI*190*t)*exp(-16*t)+if(gte(t,0.16),sin(2*PI*150*(t-0.16))"
                "*exp(-16*(t-0.16)),0))':s=48000:d=1.4[a];"
                "aevalsrc='if(gte(t,0.33),0.5*(random(0)*2-1)*exp(-5*(t-0.33)),0)':s=48000:d=1.4,"
                "highpass=f=5500[b];[a][b]amix=inputs=2:normalize=0"),
}

# Where the "hit" of each sound is, so a cue lands on the beat (seconds into the file).
HIT = {"whoosh": 0.17, "rimshot": 0.33, "cash": 0.09}


def _sung_la(path: Path, notes=(196.00, 146.83), note_d=0.23, gap=0.02):
    """Two sung "la" syllables (default G3 then D3): additive voice through /l/->/a/
    formants, with a small pitch scoop, vibrato and a short room echo."""
    import wave

    import numpy as np
    sr, tail = SR, 0.18
    n = int(sr * (len(notes) * (note_d + gap) + tail))
    out = np.zeros(n)
    L, A = (360, 1300, 2700), (730, 1090, 2440)          # formants: /l/ onset, /a/ vowel
    bw, amp = (90, 110, 170), (1.0, 0.55, 0.25)
    for j, f0 in enumerate(notes):
        m = int(sr * note_d)
        t = np.arange(m) / sr
        glide = np.clip(t / 0.06, 0, 1)                   # /l/ -> /a/ over 60 ms
        scoop = 1 - 0.02 * (1 - np.clip(t / 0.04, 0, 1))  # start 2% flat, slide up
        vib = 1 + 0.006 * np.sin(2 * np.pi * 5.5 * t) * np.clip((t - 0.08) / 0.05, 0, 1)
        f = f0 * scoop * vib
        phase = 2 * np.pi * np.cumsum(f) / sr
        sig = np.zeros(m)
        for k in range(1, int(5000 / f0)):
            fk = k * f
            g = sum(a / (1 + ((fk - (lf + (af - lf) * glide)) / (b / 2)) ** 2)
                    for lf, af, b, a in zip(L, A, bw, amp))
            sig += g * np.sin(k * phase) / k ** 0.6
        sig += 0.004 * np.random.default_rng(j).standard_normal(m)  # a little breath
        env = (0.55 + 0.45 * np.clip((t - 0.02) / 0.05, 0, 1)) * np.clip(t / 0.012, 0, 1)
        env *= np.clip((note_d - t) / 0.05, 0, 1)
        s = int(sr * j * (note_d + gap))
        out[s:s + m] += sig * env
    for delay, g in ((0.031, 0.28), (0.067, 0.16), (0.11, 0.08)):  # small room
        d = int(sr * delay)
        out[d:] += g * out[:-d].copy()
    out = out / (np.abs(out).max() + 1e-9) * 0.8
    pcm = (np.repeat(out[:, None], 2, axis=1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(pcm.tobytes())


# Sounds generated in Python instead of a lavfi graph.
PY_SOUNDS = {"lala": _sung_la}
LIBRARY["lala"] = None  # "la la", G3 then D3 (Gilmore montage title-card buffer)


# ---------- soundboard: sounds the user kept from the show itself ----------
SOUNDBOARD = DATA_DIR / "sfx" / "soundboard.json"


def soundboard() -> list:
    if SOUNDBOARD.exists():
        import json
        return json.loads(SOUNDBOARD.read_text(encoding="utf-8"))
    return []


def _register_soundboard():
    for s in soundboard():
        LIBRARY.setdefault(s["name"], None)


def save_sound(name: str, episode: str, start: float, end: float, gain: float = 1.0, file: str = None) -> dict:
    """Cut [start, end] of an episode's audio (full quality source), or of an audio/video
    file the user provides, into the soundboard."""
    import json
    import re
    from . import library
    name = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")
    if not name:
        raise ValueError("name the sound")
    if name in LIBRARY and name not in {s["name"] for s in soundboard()}:
        raise ValueError(f"'{name}' is a built-in sound; pick another name")
    if not 0.05 <= end - start <= 10:
        raise ValueError("sounds must be 0.05-10 seconds")
    if file:
        if not Path(file).is_file():
            raise ValueError(f"no such file: {file}")
        src = str(Path(file))
    else:
        src = library.episode(episode)["source"]
    d = DATA_DIR / "sfx"
    d.mkdir(exist_ok=True)
    dur = end - start
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
                    "-i", src, "-vn", "-ac", "2", "-ar", str(SR),
                    "-af", f"volume={gain},afade=t=in:d=0.015,afade=t=out:st={max(0, dur - 0.04):.3f}:d=0.04",
                    str(d / f"{name}.wav")], check=True)
    meta = {"name": name, "episode": episode, "file": file, "start": round(start, 3), "end": round(end, 3), "gain": gain}
    sounds = [s for s in soundboard() if s["name"] != name] + [meta]
    SOUNDBOARD.write_text(json.dumps(sounds, indent=1), encoding="utf-8")
    LIBRARY.setdefault(name, None)
    return meta


def delete_sound(name: str):
    import json
    sounds = soundboard()
    if name not in {s["name"] for s in sounds}:
        raise KeyError(name)
    SOUNDBOARD.write_text(json.dumps([s for s in sounds if s["name"] != name], indent=1), encoding="utf-8")
    (DATA_DIR / "sfx" / f"{name}.wav").unlink(missing_ok=True)
    LIBRARY.pop(name, None)


_register_soundboard()


def sfx_file(name: str) -> Path:
    if name not in LIBRARY:
        raise KeyError(f"unknown sfx '{name}' (have: {', '.join(LIBRARY)})")
    d = DATA_DIR / "sfx"
    d.mkdir(exist_ok=True)
    p = d / f"{name}.wav"
    if not p.exists():
        if LIBRARY[name] is None and name not in PY_SOUNDS:
            raise FileNotFoundError(f"soundboard sound '{name}' is missing its file")
        if name in PY_SOUNDS:
            PY_SOUNDS[name](p)
        else:
            subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                            "-i", LIBRARY[name], "-ac", "2", "-ar", str(SR), str(p)], check=True)
    return p
