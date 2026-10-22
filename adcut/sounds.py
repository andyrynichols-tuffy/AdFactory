"""The soundboard: short sound effects to drop onto takes. Every sound is synthesized
here (a small numpy synth + Meme Factory's comedy library), so there's nothing
recorded and nothing to license. Each one is "punched up" (soft saturation, peak at
-0.5 dBFS) so it cuts through his voice. Generated once into DATA_DIR/ads/sfx/."""
import wave
from pathlib import Path

import numpy as np

from supercut import sfx as memesfx

from . import store

SFX_DIR = store.AD_DATA / "sfx"
SFX_DIR.mkdir(parents=True, exist_ok=True)
SR = 48000
VERSION = 8  # bump to regenerate everything after changing the synth


# ---------- layered synth ----------
# Every sound is a stack of layers that read as one hit: a crisp transient up front,
# a body of slightly detuned voices (left/right) for thickness, a sub for weight, air
# on top, and a short stereo room so it sits in a space. Signals are (2, n) stereo.

def _t(d):
    return np.arange(int(SR * d)) / SR


def _n(d):
    return int(SR * d)


def _env(n, attack=0.004, decay=6.0):
    t = np.arange(n) / SR
    return np.minimum(1, t / max(attack, 1e-4)) * np.exp(-decay * t)


def _noise(d, seed=0):
    return np.random.default_rng(seed).standard_normal(_n(d))


def _fft_conv(x, h):
    n = len(x) + len(h) - 1
    N = 1 << (n - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(x, N) * np.fft.rfft(h, N), N)[:n]


def _onepole(x, cutoff):
    """One-pole low-pass via scipy-free recursion done on blocks with numpy (fast enough)."""
    a = np.exp(-2 * np.pi * np.clip(cutoff, 20, SR / 2.2) / SR)
    if np.ndim(a) == 0:
        # closed form with lfilter-like trick: y[n] = (1-a) x[n] + a y[n-1]
        y = np.empty_like(x)
        acc = 0.0
        b = 1 - a
        for i in range(len(x)):
            acc = b * x[i] + a * acc
            y[i] = acc
        return y
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc = (1 - a[i]) * x[i] + a[i] * acc
        y[i] = acc
    return y


def _lp(x, cutoff):
    return _onepole(x, cutoff)


def _hp(x, cutoff):
    return x - _onepole(x, cutoff)


def _st(l, r=None):
    r = l if r is None else r
    n = max(len(l), len(r))
    out = np.zeros((2, n))
    out[0, :len(l)] += l
    out[1, :len(r)] += r
    return out


def _mix(length, *parts):
    """parts = (start seconds, stereo or mono signal, gain[, pan -1..1])"""
    out = np.zeros((2, _n(length)))
    for p in parts:
        at, sig, g = p[0], p[1], p[2]
        pan = p[3] if len(p) > 3 else 0.0
        sig = _st(sig) if np.ndim(sig) == 1 else sig
        if pan:
            sig = sig * np.array([[min(1, 1 - pan)], [min(1, 1 + pan)]])
        i = int(at * SR)
        k = min(sig.shape[1], out.shape[1] - i)
        if k > 0:
            out[:, i:i + k] += g * sig[:, :k]
    return out


def _room(x, wet=0.25, size=0.8, bright=7000, seed=0):
    """Short stereo room: decorrelated decaying-noise impulse responses per side."""
    n = _n(size)
    t = np.arange(n) / SR
    pre = _n(0.012)
    shared = np.random.default_rng(seed * 7).standard_normal(n)
    out = []
    for side in (0, 1):
        own = np.random.default_rng(seed * 7 + side + 1).standard_normal(n)
        ir = (0.75 * shared + 0.66 * own) * np.exp(-6.5 * t / size)  # mostly shared: solid in mono
        ir = _lp(ir, bright)
        ir = np.concatenate([np.zeros(pre), ir])
        ir /= np.sqrt((ir ** 2).sum()) + 1e-9
        out.append(_fft_conv(x[side], ir))
    rev = np.array(out)
    dry = np.zeros_like(rev)
    dry[:, :x.shape[1]] = x
    return dry + 0.6 * wet * rev * (np.abs(x).max() / (np.abs(rev).max() + 1e-9))


def _transient(gain=1.0, ms=6, hp=2500, seed=1):
    d = ms / 1000
    return _hp(_noise(d, seed), hp) * _env(_n(d), 0.0005, 700 / ms) * gain


def _sub(f, d=0.3, decay=12, gain=1.0):
    t = _t(d)
    fr = f * (1 + 0.6 * np.exp(-40 * t))  # tiny pitch drop = punch
    return np.sin(2 * np.pi * np.cumsum(fr) / SR) * _env(len(t), 0.002, decay) * gain


def _air(d, decay=4, gain=1.0, seed=3, attack=0.01):
    return _hp(_noise(d, seed), 7500) * _env(_n(d), attack, decay) * gain


def _bell1(f, d, decay, bright, t):
    parts = [(1, 1.0), (2.0, 0.55 * bright), (2.76, 0.4 * bright), (5.4, 0.2 * bright), (8.93, 0.09 * bright)]
    return sum(a * np.sin(2 * np.pi * f * m * t) * np.exp(-decay * (1 + 0.55 * m) * t) for m, a in parts)


def _bell(f, d=1.0, decay=5.0, bright=1.0, cents=7):
    """Detuned bell: left a few cents flat, right a few sharp (width + shimmer)."""
    t = _t(d)
    att = np.minimum(1, t / 0.0015)
    k = 2 ** (cents / 1200)
    mid = _bell1(f, d, decay, bright, t)
    return np.array([(mid + 0.45 * _bell1(f / k, d, decay, bright, t)) * att,
                     (mid + 0.45 * _bell1(f * k, d, decay, bright, t)) * att])


def _osc(f, t, kind):
    ph = 2 * np.pi * (np.cumsum(f) / SR if np.ndim(f) else f * t)
    if kind == "square":
        return np.tanh(3.5 * np.sin(ph))
    if kind == "saw":
        return 2 * ((ph / (2 * np.pi)) % 1) - 1
    return np.sin(ph)


def _voice(f, d, kind="sine", decay=4.0, attack=0.004, cents=9, n=3):
    """n detuned voices spread across the stereo field."""
    t = _t(d)
    env = _env(len(t), attack, decay)
    L, R = np.zeros(len(t)), np.zeros(len(t))
    for i in range(n):
        c = (i - (n - 1) / 2) * cents
        ff = (np.asarray(f) if np.ndim(f) else f) * 2 ** (c / 1200)
        s = _osc(ff, t, kind)
        pan = (i - (n - 1) / 2) / max(1, (n - 1) / 2)
        L += s * (1 - 0.3 * pan)
        R += s * (1 + 0.3 * pan)
    return np.array([L, R]) * env / n


C4, E4, G4 = 261.63, 329.63, 392.0
C5, D5, E5, G5, A5, B5 = 523.25, 587.33, 659.25, 783.99, 880.0, 987.77
C6, E6, G6, C7, E7 = 1046.5, 1318.5, 1568.0, 2093.0, 2637.0


def _sparkle():
    notes = [C6, E6, G6, C7, E7]
    x = _mix(1.4, (0, _transient(0.5, 4, 5000), 1),
             *[(i * 0.045, _bell(f, 1.0, 5.5, 1.3, 8), 0.55, (i - 2) * 0.25) for i, f in enumerate(notes)],
             (0, _air(1.2, 3.5, 1.0, attack=0.08), 0.12), (0, _sub(C5 / 2, 0.25, 14), 0.25))
    return _room(x, 0.38, 1.2)


def _twinkle():
    rng = np.random.default_rng(7)
    x = _mix(1.4, *[(rng.uniform(0, 0.55), _bell(rng.choice([C7, 2349.3, E7, 3136.0, 3520.0]), 0.6, 8, 1.4), 0.4, rng.uniform(-0.8, 0.8))
                    for _ in range(12)], (0, _air(1.0, 3, attack=0.1), 0.1))
    return _room(x, 0.45, 1.3)


def _magic():
    d = 1.4
    t = _t(d)
    f = 450 * 2 ** (3.3 * np.minimum(1, t / 0.9))
    gl = _voice(f * (1 + 0.01 * np.sin(2 * np.pi * 6 * t)), d, "sine", 1.6, 0.04, 12)
    sw = _st(_hp(_noise(d, 9), 3000) * np.sin(np.pi * np.minimum(1, t / 1.0)) ** 2)
    x = _mix(1.6, (0, gl, 0.5), (0, sw, 0.12), (0.5, _twinkle(), 0.7))
    return _room(x, 0.4, 1.2)


def _bling():
    d = 1.3
    t = _t(d)
    idx = 4 * np.exp(-6 * t)
    car = 2400
    fm = lambda k: np.sin(2 * np.pi * car * k * t + idx * np.sin(2 * np.pi * car * 3.5 * t)) * np.exp(-3.2 * t) * np.minimum(1, t / 0.001)
    body = np.array([fm(1) + 0.4 * fm(0.996), fm(1) + 0.4 * fm(1.004)])
    x = _mix(d, (0, _transient(0.8, 3, 6000), 1), (0, body, 0.6), (0, _bell(C7, 1.2, 4, 1.5), 0.4), (0, _air(0.8, 5), 0.15))
    return _room(x, 0.3, 1.0)


def _success():
    x = _mix(1.6, (0, _transient(0.6, 5, 3000), 1), (0, _bell(G5, 1.3, 3.5), 0.55), (0, _sub(G4 / 2, 0.3, 10), 0.4),
             (0.14, _bell(C6, 1.4, 2.8), 0.6), (0.14, _bell(E6, 1.4, 2.8), 0.45), (0.14, _bell(G6, 1.4, 3.0), 0.3),
             (0.14, _sub(C4 / 2, 0.4, 8), 0.5), (0.14, _transient(0.5, 4, 4000, 2), 1))
    return _room(x, 0.3, 1.1)


def _double_ding():
    x = _mix(1.4, (0, _transient(0.7, 4, 4000), 1), (0, _bell(E6, 1.1, 3.8, 1.2), 0.75, -0.2), (0, _sub(E5 / 4, 0.2, 14), 0.3),
             (0.17, _transient(0.7, 4, 4000, 2), 1), (0.17, _bell(G6, 1.2, 3.4, 1.2), 0.75, 0.2), (0.17, _sub(G5 / 4, 0.25, 12), 0.3))
    return _room(x, 0.25, 0.9)


def _level_up():
    notes = [C5, E5, G5, C6, E6, G6]
    x = _mix(1.0, *[(i * 0.065, _voice(f, 0.2, "square", 9, 0.002, 10), 0.4) for i, f in enumerate(notes)],
             *[(i * 0.065, _transient(0.35, 3, 3500, i), 1) for i in range(len(notes))],
             *[(i * 0.065, _voice(f / 2, 0.18, "square", 10, 0.002, 6, 2), 0.18) for i, f in enumerate(notes)],
             (0.39, _voice(C7 * (1 + 0.006 * np.sin(2 * np.pi * 7 * _t(0.55))), 0.55, "square", 4, 0.002, 12), 0.4),
             (0.39, _sub(C5 / 2, 0.3, 9), 0.4))
    return _room(x, 0.18, 0.7)


def _coin():
    x = _mix(0.9, (0, _transient(0.6, 3, 4000), 1), (0, _voice(B5 * 2, 0.085, "square", 1, 0.001, 8), 0.5),
             (0.08, _voice(E6 * 2, 0.6, "square", 6, 0.001, 8), 0.5), (0.08, _bell(E7, 0.7, 6, 1.4), 0.25))
    return _room(x, 0.22, 0.8)


def _cha_ching():
    rng = np.random.default_rng(5)
    thump = _st(_lp(_noise(0.12, 8), 900) * _env(_n(0.12), 0.001, 35))
    ka = _st(_hp(_noise(0.06, 9), 2500) * _env(_n(0.06), 0.001, 60))
    jingle = [(0.12 + rng.uniform(0, 0.25), _bell(rng.uniform(3000, 5200), 0.35, 12, 1.5), 0.18, rng.uniform(-0.7, 0.7)) for _ in range(8)]
    x = _mix(1.6, (0, thump, 0.9), (0, _sub(70, 0.2, 18), 0.6), (0.02, ka, 0.7), (0.1, _transient(0.7, 3, 5000), 1),
             (0.1, _bell(C7, 1.3, 2.6, 1.4), 0.6, -0.15), (0.1, _bell(E7, 1.3, 2.8, 1.3), 0.45, 0.15), *jingle)
    return _room(x, 0.28, 1.0)


def _tada():
    d = 2.0
    t = _t(d)

    def brass(f, start, length):
        tt = np.maximum(0, t - start)
        on = (t >= start) & (t < start + length)
        env = np.where(on, np.minimum(1, tt / 0.012), 0) * np.where(t < start + length, 1, 0)
        cut = 900 + 4500 * np.minimum(1, tt / 0.06) * np.exp(-1.2 * tt)
        L = sum(_osc(f * 2 ** (c / 1200), t, "saw") for c in (-9, 0))
        R = sum(_osc(f * 2 ** (c / 1200), t, "saw") for c in (0, 9))
        return np.array([_lp(L * env, cut), _lp(R * env, cut)])

    chord = lambda s, l: sum(brass(f, s, l) for f in (C5, E5, G5, C6))
    hold = 1.6
    tail = np.where(t >= 0.17, np.exp(-1.3 * np.maximum(0, t - 0.17 - 0.25)).clip(0, 1), 1)
    snare = _mix(0.18, (0, _hp(_noise(0.18, 21), 1200) * _env(_n(0.18), 0.001, 22), 1), (0, _sub(190, 0.12, 30), 0.6))
    crash = _st(_hp(_noise(1.6, 22), 4500) * _env(_n(1.6), 0.002, 2.2), _hp(_noise(1.6, 23), 4500) * _env(_n(1.6), 0.002, 2.2))
    x = _mix(d, (0, chord(0, 0.12), 0.09), (0.17, chord(0.0, hold) * tail[None, :], 0.09),
             (0, snare, 0.5), (0, _sub(65, 0.25, 14), 0.6), (0.17, crash, 0.35), (0.17, _sub(55, 0.4, 9), 0.7),
             (0.17, _transient(0.8, 5, 2500, 4), 1))
    return _room(x, 0.3, 1.2)


def _party():
    d = 1.0
    t = _t(d)
    f = 320 + 240 * np.minimum(1, t / 0.22)
    body = _voice(f * (1 + 0.01 * np.sin(2 * np.pi * 30 * t)), d, "saw", 0.6, 0.008, 14)
    rasp = _st(_lp(_noise(d, 31), 3000) * (0.5 + 0.5 * np.sin(2 * np.pi * 30 * t)))
    shape = np.minimum(1, t / 0.01) * np.where(t < 0.78, 1, np.exp(-25 * (t - 0.78)))
    x = _mix(1.2, (0, np.array([_lp(body[0], 2800), _lp(body[1], 2800)]) * shape, 0.7), (0, rasp * shape, 0.12),
             (0, _transient(0.5, 6, 2000), 1))
    return _room(x, 0.2, 0.8)


def _applause():
    d = 2.4
    rng = np.random.default_rng(11)
    out = np.zeros((2, _n(d)))
    for _ in range(320):
        at = rng.uniform(0, d - 0.1)
        clap = _hp(_noise(0.05, int(rng.integers(1e6))), 1100) * _env(_n(0.05), 0.0008, 80) * rng.uniform(0.3, 1)
        pan = rng.uniform(-0.9, 0.9)
        i = int(at * SR)
        out[0, i:i + len(clap)] += clap * (1 - 0.5 * pan)
        out[1, i:i + len(clap)] += clap * (1 + 0.5 * pan)
    t = np.arange(out.shape[1]) / SR
    crowd = _st(_lp(_hp(_noise(d, 41), 400), 2500), _lp(_hp(_noise(d, 42), 400), 2500)) * 0.25
    shape = np.minimum(1, t / 0.2) * np.where(t < 1.8, 1, np.exp(-5 * (t - 1.8)))
    return _room((out + crowd) * shape, 0.3, 1.0)


def _swoosh(up=True, d=0.7):
    t = _t(d)
    prog = (t / d) if up else (1 - t / d)
    cut = 500 + 7500 * prog ** 2
    nz = lambda seed: _onepole(_noise(d, seed), cut) - 0.6 * _onepole(_noise(d, seed), cut * 0.25)
    mid, a, b = nz(5), nz(6), nz(7)
    L, R = mid + 0.35 * a, mid + 0.35 * b  # mostly shared noise: wide but solid on a phone
    shape = np.sin(np.pi * t / d) ** 1.6
    tone = _voice(220 * 2 ** (2 * prog), d, "sine", 0.1, 0.05, 15)
    x = np.array([L, R]) * shape + 0.12 * tone * shape
    return _room(x, 0.22, 0.9)


def _swoosh_up():
    return _swoosh(True)


def _swoosh_down():
    return _swoosh(False)


def _whoosh2():
    return _swoosh(True, 0.42)


def _pop():
    d = 0.2
    t = _t(d)
    f = 300 + 900 * np.exp(-30 * t)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(len(t), 0.0008, 26)
    x = _mix(d, (0, _transient(0.9, 2, 3000), 1), (0, body, 0.9), (0, _sub(110, 0.12, 30), 0.4))
    return _room(x, 0.1, 0.4)


def _bubble():
    d = 0.22
    t = _t(d)
    f = 380 + 1600 * (t / d) ** 0.7
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(len(t), 0.002, 16)
    x = _mix(d, (0, _transient(0.4, 2, 4000), 1), (0, _st(body * 0.9, body * 0.85), 1))
    return _room(x, 0.15, 0.5)


def _heart():
    x = _mix(1.0, (0, _voice(E6, 0.3, "sine", 7, 0.01, 10), 0.6), (0, _voice(E5, 0.3, "sine", 7, 0.01, 6), 0.3),
             (0.16, _voice(G6, 0.6, "sine", 4, 0.01, 10), 0.6), (0.16, _voice(G5, 0.6, "sine", 4, 0.01, 6), 0.3),
             (0, _air(0.6, 5, attack=0.05), 0.05))
    return _room(x, 0.35, 1.0)


def _reveal():
    d = 2.6
    roll = np.zeros((2, _n(1.3)))
    for k in range(52):
        at = k * 0.024
        hit = _hp(_noise(0.03, k), 400) * _env(_n(0.03), 0.0008, 90) * (0.2 + 0.8 * k / 52)
        i = int(at * SR)
        side = k % 2
        roll[side, i:i + len(hit)] += hit
        roll[1 - side, i:i + len(hit)] += 0.6 * hit
    crash = _st(_hp(_noise(1.4, 99), 3500) * _env(_n(1.4), 0.002, 2.3), _hp(_noise(1.4, 98), 3500) * _env(_n(1.4), 0.002, 2.3))
    x = _mix(d, (0, np.array([_lp(roll[0], 4000), _lp(roll[1], 4000)]), 0.9),
             (1.25, crash, 0.8), (1.25, _sub(50, 0.6, 6), 1.0), (1.25, _transient(1, 6, 1800), 1),
             (1.25, _bell(C6, 1.2, 2.5, 1.2), 0.35), (1.25, _bell(G6, 1.2, 2.5, 1.2), 0.25))
    return _room(x, 0.3, 1.2)


def _ping():
    x = _mix(1.0, (0, _transient(0.6, 3, 4000), 1), (0, _bell(1760, 0.6, 7, 0.8), 0.6), (0.11, _bell(2637, 0.9, 4.5, 0.8), 0.6),
             (0, _sub(440, 0.15, 20), 0.2))
    return _room(x, 0.25, 0.8)


def _ding():
    x = _mix(1.6, (0, _transient(0.8, 4, 3000), 1), (0, _bell(C7 / 2, 1.5, 2.6, 1.2), 0.7), (0, _bell(C7, 1.2, 3.2, 1.0), 0.35),
             (0, _sub(C5 / 2, 0.3, 10), 0.4))
    return _room(x, 0.3, 1.1)


def _shutter():
    a = _hp(_noise(0.05, 1), 1200) * _env(_n(0.05), 0.0008, 90)
    b = _hp(_noise(0.07, 2), 900) * _env(_n(0.07), 0.0008, 60)
    body = _lp(_noise(0.05, 12), 700) * _env(_n(0.05), 0.001, 70)
    x = _mix(0.4, (0, a, 1, -0.2), (0, body, 0.6), (0.085, b, 0.9, 0.2), (0.085, body, 0.5))
    return _room(x, 0.12, 0.4)


def _click():
    t = _t(0.05)
    tick = np.sin(2 * np.pi * 1900 * t) * _env(len(t), 0.0005, 160)
    x = _mix(0.06, (0, _transient(1.0, 2, 3000), 1), (0, tick, 0.5))
    return _room(x, 0.08, 0.3)


def _thwack():
    """A hard slap/hit for a freeze frame: a sharp crack, a fat low thump, a slap of mids."""
    d = 0.55
    crack = _st(_hp(_noise(0.05, 61), 1800) * _env(_n(0.05), 0.0004, 70),
                _hp(_noise(0.05, 62), 1800) * _env(_n(0.05), 0.0004, 70))
    t = _t(0.35)
    thump = np.sin(2 * np.pi * np.cumsum(55 + 130 * np.exp(-28 * t)) / SR) * _env(len(t), 0.001, 11)
    slap = _lp(_hp(_noise(0.12, 63), 600), 3800) * _env(_n(0.12), 0.0005, 32)
    x = _mix(d, (0, crack, 0.9), (0, _st(thump), 1.0), (0, _st(slap), 0.7), (0, _transient(1.0, 4, 3000, 64), 1))
    return _room(x, 0.22, 0.5)


def _jingle():
    """A little game-show sting (~2s): bouncy lead, bass, light beat, a bright button at the end."""
    bpm = 168
    q = 60 / bpm / 2  # eighth notes
    lead = [(C5, 1), (E5, 1), (G5, 1), (C6, 1), (A5, 1), (G5, 1), (E5, 1), (G5, 1), (C6, 3)]
    bass = [(C4 / 2, 2), (G4 / 2, 2), (A5 / 8, 2), (G4 / 2, 2), (C4 / 2, 3)]
    d = q * 11 + 0.6
    parts, at = [], 0.0
    for f, n in lead:
        parts.append((at, _voice(f, q * n + 0.12, "square", 9 if n == 1 else 3.5, 0.003, 10, 3), 0.16))
        parts.append((at, _bell(f * 2, q * n + 0.1, 9, 0.6), 0.05))
        at += q * n
    at = 0.0
    for f, n in bass:
        parts.append((at, _voice(f, q * n, "saw", 6, 0.004, 6, 2), 0.18))
        at += q * n
    for k in range(10):  # hat on every eighth, snare on 2 and 4, kick on 1 and 3
        hat = _hp(_noise(0.04, 70 + k), 7000) * _env(_n(0.04), 0.0005, 80)
        parts.append((k * q, _st(hat), 0.12))
        if k % 4 == 2:
            parts.append((k * q, _st(_hp(_noise(0.12, 90 + k), 1500) * _env(_n(0.12), 0.0008, 28)), 0.28))
        if k % 4 == 0:
            parts.append((k * q, _st(_sub(60, 0.2, 18)), 0.5))
    end = q * 8  # the button: a bright stab + cymbal on the last note
    parts.append((end, _st(_hp(_noise(0.9, 99), 5000) * _env(_n(0.9), 0.002, 4)), 0.18))
    parts.append((end, _voice(C6, 0.5, "saw", 5, 0.003, 12, 3), 0.1))
    return _room(_mix(d, *parts), 0.25, 0.9)


# ---------- voices: formant synthesis (an "ahh" is a buzz shaped by the mouth) ----------
# Each harmonic of the voice's pitch is weighted by the vowel's resonances (formants), so
# the tone reads as a person; jitter, shimmer and vibrato keep it from sounding robotic,
# and breath noise through the same resonances adds air.
VOWELS = {  # (frequency, bandwidth, gain) per formant
    "a_f": [(850, 90, 1.0), (1220, 100, 0.55), (2810, 140, 0.28), (3800, 220, 0.12)],
    "a_m": [(730, 90, 1.0), (1090, 110, 0.5), (2440, 150, 0.22), (3400, 220, 0.08)],
    "o":   [(470, 70, 1.0), (840, 90, 0.45), (2550, 160, 0.12), (3400, 250, 0.05)],
    "u":   [(330, 60, 1.0), (760, 80, 0.32), (2400, 170, 0.06), (3300, 250, 0.03)],
}


def _wobble(n, rate, seed, depth):
    """Smooth random drift (jitter/shimmer): random points at `rate` Hz, interpolated."""
    k = max(2, int(n / SR * rate) + 2)
    pts = np.random.default_rng(seed).standard_normal(k)
    return 1 + depth * np.interp(np.arange(n), np.linspace(0, n, k), pts)


def _formant_gain(f, formants):
    g = 0.015
    for F, bw, a in formants:
        g = g + a / (1 + ((f - F) / (bw / 2)) ** 2)
    return g


def _morph(va, vb, m):
    """Formants moving from vowel va to vb as m goes 0 -> 1 (m is per sample)."""
    return [(Fa + (Fb - Fa) * m, ba + (bb - ba) * m, aa + (ab - aa) * m) for (Fa, ba, aa), (Fb, bb, ab) in zip(va, vb)]


def _sing(f0, vowel_a, vowel_b=None, m=None, vib=(5.4, 0.006), seed=0, breath=0.12, tilt=1.15):
    """One voice. f0 = pitch per sample. Returns mono."""
    n = len(f0)
    t = np.arange(n) / SR
    f = f0 * (1 + vib[1] * np.sin(2 * np.pi * vib[0] * t + seed)) * _wobble(n, 18, seed, 0.004)
    forms = _morph(vowel_a, vowel_b or vowel_a, m if m is not None else 0.0)
    ph = 2 * np.pi * np.cumsum(f) / SR
    out = np.zeros(n)
    for k in range(1, int(7500 / max(60, f0.min())) + 1):
        fk = k * f
        amp = _formant_gain(fk, forms) * k ** -tilt * (fk < 9000)
        out += amp * np.sin(k * ph)
    out *= _wobble(n, 12, seed + 50, 0.05)  # shimmer
    if breath:
        nz = np.fft.rfft(np.random.default_rng(seed + 9).standard_normal(n))
        fr = np.fft.rfftfreq(n, 1 / SR)
        g = _formant_gain(fr, vowel_a) * (fr > 300)
        out += breath * np.fft.irfft(nz * g, n) * np.abs(out).max() / 3
    return out


def _angel_ahh():
    """Heavenly choir "aaah": a big major chord of detuned voices that swells in fast
    (punchy on a beat) and blooms in a large hall, with a glint of bells on top."""
    d = 2.6
    t = _t(d)
    rise = np.clip(t / 0.38, 0, 1)
    swell = (0.5 - 0.5 * np.cos(np.pi * rise)) * np.where(t < 1.8, 1, np.exp(-3.0 * (t - 1.8)))  # eases in, no jolt
    parts = []
    for i, (f, g) in enumerate([(261.63, 0.8), (329.63, 0.7), (392.0, 0.7), (523.25, 0.65), (659.25, 0.45), (783.99, 0.3)]):
        for j, c in enumerate((-9, 0, 8)):
            v = _sing(np.full(len(t), f * 2 ** (c / 1200)), VOWELS["a_f"], vib=(5.0 + 0.4 * j, 0.007), seed=i * 7 + j, breath=0.18)
            parts.append((0.012 * j, v * swell, g, (j - 1) * 0.55))
    parts += [(0.25, _bell(C6, 1.6, 3.0, 0.5), 0.03), (0.32, _bell(E6, 1.4, 3.4, 0.5), 0.022),
              (0, _air(1.8, 1.8, 0.6, 7, 0.3), 0.05)]
    return _room(_mix(d, *parts), 0.6, 2.2, 6500, 5)


def _sigh_ahh():
    """Relieved "ahhh": a breathy voice that starts up high and settles down, airy at both ends."""
    d = 1.5
    t = _t(d)
    f0 = 105 + 95 * np.exp(-2.6 * t) + 8 * np.exp(-12 * t)
    m = np.minimum(1, t / 1.3)
    v = _sing(f0, VOWELS["a_m"], VOWELS["o"], m * 0.35, vib=(4.6, 0.004), seed=3, breath=0.45, tilt=1.35)
    voiced = (0.5 - 0.5 * np.cos(np.pi * np.clip((t - 0.06) / 0.22, 0, 1))) * np.where(t < 0.85, 1, np.exp(-4.2 * (t - 0.85)))
    hiss = _lp(_hp(_noise(d, 41), 700), 5200) * np.clip(t / 0.12, 0, 1) * np.exp(-1.6 * t)  # breath leads the voice
    exhale = _lp(_hp(_noise(d, 42), 400), 3000) * np.clip((t - 0.8) / 0.3, 0, 1) * np.exp(-3 * np.maximum(0, t - 1.0))
    x = _mix(d, (0, _st(v * voiced), 1.0), (0, _st(hiss), 0.035), (0, _st(exhale), 0.05))
    return _room(x, 0.18, 0.5, 6000, 8)


def _crowd_ooh():
    """A room full of people going "ooooh": many voices, staggered, rising then falling."""
    d = 1.9
    rng = np.random.default_rng(11)
    parts = []
    for i in range(16):
        start, length = rng.uniform(0, 0.12), rng.uniform(1.15, 1.6)
        t = _t(length)
        base = rng.uniform(105, 290)
        f0 = base * 2 ** ((3 * np.minimum(1, t / 0.35) - 6 * np.clip((t - 0.45) / (length - 0.45), 0, 1)) / 12)
        v = _sing(f0, VOWELS["u"], VOWELS["o"], np.minimum(1, t / 0.5), vib=(rng.uniform(4.5, 6), 0.008), seed=100 + i,
                  breath=0.3, tilt=1.3)
        a = rng.uniform(0.18, 0.32)
        env = (0.5 - 0.5 * np.cos(np.pi * np.clip(t / a, 0, 1))) * np.where(t < length - 0.45, 1, np.exp(-6 * (t - (length - 0.45))))
        parts.append((start, v * env, rng.uniform(0.5, 1.0), rng.uniform(-0.8, 0.8)))
    murmur = _lp(_hp(_noise(d, 13), 300), 2500) * np.minimum(1, _t(d) / 0.1) * np.exp(-1.8 * _t(d))
    parts.append((0, _st(murmur, _lp(_hp(_noise(d, 14), 300), 2500) * np.minimum(1, _t(d) / 0.1) * np.exp(-1.8 * _t(d))), 0.04))
    return _room(_mix(d, *parts), 0.35, 1.2, 6000, 12)


def _slide(up=True):
    """Slide whistle: a breathy pipe swooping up (or down) with a little vibrato at the end."""
    d = 0.85
    t = _t(d)
    k = np.clip(t / 0.62, 0, 1) ** (0.8 if up else 1.2)
    f = 650 * (2200 / 650) ** (k if up else 1 - k)
    f = f * (1 + 0.012 * np.sin(2 * np.pi * 7 * t) * np.clip((t - 0.45) / 0.2, 0, 1))
    ph = 2 * np.pi * np.cumsum(f) / SR
    tone = np.sin(ph) + 0.18 * np.sin(2 * ph) + 0.05 * np.sin(3 * ph)
    breath = _noise(d, 21) * np.sin(ph) * 0.25  # air riding the pitch
    env = np.minimum(1, t / 0.02) * np.where(t < 0.7, 1, np.exp(-14 * (t - 0.7)))
    sig = (tone + breath) * env
    x = _mix(d, (0, _st(sig, sig * 0.97), 0.8), (0, _air(0.3, 9, 1, 22, 0.005), 0.08))
    return _room(x, 0.15, 0.4)


def _slide_up():
    return _slide(True)


def _slide_down():
    return _slide(False)


def _bass_drop():
    """Bass drop: a kick and a deep, gritty sub diving down, with a low rumble under it."""
    d = 1.9
    t = _t(d)
    f = 38 + 120 * np.exp(-5.5 * t)
    sub = np.tanh(2.2 * np.sin(2 * np.pi * np.cumsum(f) / SR)) * np.minimum(1, t / 0.004) * np.exp(-1.25 * t)
    grit = _lp(np.tanh(4 * np.sin(2 * np.pi * np.cumsum(f * 2) / SR)), 900) * np.exp(-2.2 * t)
    rumble = _lp(_noise(d, 31), 180) * np.exp(-1.6 * t)
    x = _mix(d, (0, _st(sub), 1.0), (0, _st(grit), 0.25), (0, _st(rumble), 0.5),
             (0, _transient(1.0, 6, 2000, 32), 0.9), (0, _st(_sub(62, 0.3, 14)), 0.8))
    return _room(x, 0.12, 0.6, 3000, 30)


def _dun_dun():
    """Dramatic sting "dun, dun, DUNNN": low brass/strings stabs with timpani, the last one
    lower and long with a cymbal swell."""
    d = 2.6

    def stab(freqs, length, decay):
        t = _t(length)
        cut = 500 + 2800 * np.exp(-6 * t)
        env = np.minimum(1, t / 0.012) * np.exp(-decay * t)
        out = np.zeros((2, len(t)))
        for f in freqs:
            for side, c in ((0, -7), (1, 7)):
                v = sum(_osc(f * 2 ** ((c + e) / 1200), t, "saw") for e in (-4, 4))
                out[side] += _lp(v * env, cut)
        return out / len(freqs)

    def timp(f, length):
        t = _t(length)
        return _st(np.sin(2 * np.pi * np.cumsum(f * (1 + 0.15 * np.exp(-20 * t))) / SR) * _env(len(t), 0.002, 3.5)
                   + 0.3 * _lp(_noise(length, int(f)), 900) * _env(len(t), 0.001, 25))

    A2, E3, A3, F2, C3, F3 = 110.0, 164.81, 220.0, 87.31, 130.81, 174.61
    cym = _hp(_noise(2.0, 51), 5000) * np.minimum(1, _t(2.0) / 0.8) * np.exp(-1.4 * np.maximum(0, _t(2.0) - 0.8))
    x = _mix(d, (0.0, stab((A2, E3, A3), 0.34, 7), 0.6), (0.0, timp(55, 0.5), 0.8),
             (0.33, stab((A2, E3, A3), 0.34, 7), 0.6), (0.33, timp(55, 0.5), 0.8),
             (0.66, stab((F2, C3, F3, F2 / 2), 1.9, 1.3), 0.75), (0.66, timp(44, 1.4), 1.0),
             (0.66, _st(cym * 0.5, cym * 0.45), 0.12))
    return _room(x, 0.4, 1.8, 5000, 50)


def _heartbeat():
    """Heartbeat: lub-dub, lub-dub. Deep thumps with a soft flesh click, felt more than heard."""
    d = 1.6

    def beat(f, gain):
        t = _t(0.25)
        body = np.sin(2 * np.pi * np.cumsum(f * (1 + 0.35 * np.exp(-30 * t))) / SR) * _env(len(t), 0.003, 16)
        click = _lp(_noise(0.25, int(f)), 400) * _env(len(t), 0.001, 60)
        return _st(body + 0.4 * click) * gain

    x = _mix(d, (0.0, beat(55, 1.0), 1), (0.2, beat(48, 0.7), 1), (0.8, beat(55, 1.0), 1), (1.0, beat(48, 0.7), 1))
    return _room(x, 0.08, 0.3, 1500, 60)


def _whip():
    """Whip-pan swish: air tearing past, getting brighter, ending in a crack."""
    d = 0.45
    t = _t(d)
    cut = 300 + 7000 * np.clip(t / 0.13, 0, 1) ** 2
    env = np.clip(t / 0.12, 0, 1) ** 2 * np.where(t < 0.13, 1, np.exp(-28 * (t - 0.13)))
    L = _lp(_noise(d, 71), cut) - _lp(_lp(_noise(d, 71), cut), 250)
    R = _lp(_noise(d, 72), cut) - _lp(_lp(_noise(d, 72), cut), 250)
    x = _mix(d, (0, _st(L * env, R * env), 0.9), (0.125, _transient(1.0, 5, 3000, 73), 0.8),
             (0.125, _st(_sub(90, 0.12, 30)), 0.3))
    return _room(x, 0.15, 0.4)


# ---------- punchline stings, rebuilt to title-card quality (layered, real-sounding) ----------

def _bp(x, lo, hi):
    return _lp(_hp(x, lo), hi)


def _snare(seed=0, tone=190, d=0.35):
    """A real snare: stick crack, drum-head tone (two modes), wires, short room."""
    t = _t(d)
    head = (np.sin(2 * np.pi * tone * t) * np.exp(-28 * t) + 0.5 * np.sin(2 * np.pi * tone * 1.6 * t) * np.exp(-36 * t))
    wires = _bp(_noise(d, seed), 1800, 9000) * np.exp(-14 * t)
    crack = _hp(_noise(0.012, seed + 1), 3000) * _env(_n(0.012), 0.0003, 400)
    return _mix(d, (0, _st(head), 0.8), (0, _st(wires * 0.9, _bp(_noise(d, seed + 2), 1800, 9000) * np.exp(-14 * t) * 0.9), 0.7),
                (0, _st(crack), 1.0))


def _tom(f=120, seed=0, d=0.45):
    t = _t(d)
    body = np.sin(2 * np.pi * np.cumsum(f * (1 + 0.5 * np.exp(-30 * t))) / SR) * np.exp(-9 * t)
    stick = _bp(_noise(0.02, seed), 1500, 7000) * _env(_n(0.02), 0.0003, 200)
    return _mix(d, (0, _st(body), 1.0), (0, _st(stick), 0.6))


def _crash(d=1.8, seed=0, bright=1.0):
    """Cymbal: dense inharmonic shimmer + noise wash, slow decay, wide."""
    t = _t(d)
    rng = np.random.default_rng(seed)
    parts = sum(np.sin(2 * np.pi * f * t + rng.uniform(0, 6)) for f in rng.uniform(3000, 11000, 40)) / 40
    wash_l = _hp(_noise(d, seed + 1), 4500) * 0.8 + parts
    wash_r = _hp(_noise(d, seed + 2), 4500) * 0.8 + parts
    env = np.minimum(1, t / 0.003) * np.exp(-2.4 * t / bright)
    return _st(wash_l * env, wash_r * env)


def _rimshot():
    """Ba-dum-tss: snare, low tom, then the cymbal ringing out."""
    x = _mix(1.9, (0.0, _snare(31, 200), 0.85), (0.16, _tom(105, 32), 0.9), (0.16, _st(_sub(55, 0.3, 10)), 0.4),
             (0.36, _snare(33, 210), 0.5), (0.36, _crash(1.5, 34), 0.55), (0.36, _st(_sub(48, 0.25, 12)), 0.3))
    return _room(x, 0.22, 0.9, 7000, 3)


def _scratch():
    """Record scratch: a bit of 'music' on vinyl dragged back and forth under the hand."""
    base_d = 1.2
    t0 = _t(base_d)
    rng = np.random.default_rng(41)
    music = (sum(np.sin(2 * np.pi * f * t0) * a for f, a in ((110, .6), (220, .4), (330, .25), (440, .2), (660, .1)))
             + 0.6 * _bp(_noise(base_d, 42), 400, 5000))
    d = 0.62
    t = _t(d)
    # hand gesture: back, forward, back fast ("wikka-wikka"), positions in seconds of the record
    rate = np.interp(t, [0, .06, .17, .24, .33, .4, .5, .62], [1, -2.6, -2.9, 3.2, 3.0, -3.4, -1.0, 0])
    pos = 0.4 + np.cumsum(rate) / SR
    idx = np.clip((pos * SR).astype(int), 0, len(music) - 1)
    sig = music[idx] * (0.4 + 0.6 * np.minimum(1, np.abs(rate) / 2))  # louder when it moves fast
    sig = np.tanh(1.8 * sig)
    crackle = (rng.random(_n(d)) > 0.9985) * rng.uniform(-1, 1, _n(d)) * 0.8
    x = _mix(d + 0.15, (0, _st(_hp(sig, 120)), 0.9), (0, _st(crackle), 0.6), (0, _transient(0.6, 4, 2000, 43), 1))
    return _room(x, 0.12, 0.4)


def _gavel():
    """Judge's gavel: two wooden knocks on a block (wood modes + thud), in a hall."""
    def knock(seed, gain):
        d = 0.35
        t = _t(d)
        modes = sum(a * np.sin(2 * np.pi * f * t) * np.exp(-k * t) for f, a, k in ((420, 1, 32), (690, .7, 40), (1130, .5, 55), (1870, .3, 70)))
        thud = np.sin(2 * np.pi * np.cumsum(90 * (1 + np.exp(-40 * t))) / SR) * np.exp(-22 * t)
        click = _bp(_noise(0.01, seed), 1200, 6000) * _env(_n(0.01), 0.0002, 500)
        return _mix(d, (0, _st(modes), 0.7 * gain), (0, _st(thud), 0.8 * gain), (0, _st(click), gain))
    return _room(_mix(1.1, (0, knock(51, 1.0), 1), (0.24, knock(52, 1.1), 1)), 0.35, 1.1, 5000, 5)


def _buzzer():
    """Game-show wrong-answer buzzer: a fat, nasty two-tone square with a hard edge."""
    d = 0.85
    t = _t(d)
    env = np.minimum(1, t / 0.006) * np.where(t < 0.7, 1, np.exp(-30 * (t - 0.7)))
    tone = sum(_osc(f, t, "square") for f in (98, 104.5, 196.5)) / 3
    grit = np.tanh(3 * tone) * (1 + 0.3 * np.sin(2 * np.pi * 31 * t))
    body = _lp(grit, 2400) * env
    x = _mix(d, (0, _st(body, _lp(np.tanh(3 * sum(_osc(f, t, "square") for f in (98.6, 104, 197)) / 3), 2400) * env), 0.9),
             (0, _transient(0.8, 5, 1500, 61), 1), (0, _st(_sub(49, 0.7, 2)), 0.35))
    return _room(x, 0.12, 0.4)


def _boom():
    """Cinematic boom: a hit, a deep sub drop and a long dark tail."""
    d = 2.6
    t = _t(d)
    sub = np.tanh(1.6 * np.sin(2 * np.pi * np.cumsum(32 + 70 * np.exp(-6 * t)) / SR)) * np.minimum(1, t / 0.003) * np.exp(-1.3 * t)
    punch = _lp(_noise(0.4, 71), 700) * np.exp(-12 * _t(0.4))
    rumble = _lp(_noise(d, 72), 150) * np.exp(-1.1 * t)
    air = _bp(_noise(1.2, 73), 2000, 8000) * np.exp(-4 * _t(1.2))
    x = _mix(d, (0, _st(sub), 1.0), (0, _st(punch), 0.7), (0, _st(rumble, _lp(_noise(d, 74), 150) * np.exp(-1.1 * t)), 0.6),
             (0, _st(air), 0.12), (0, _transient(1.0, 6, 1500, 75), 0.9))
    return _room(x, 0.35, 2.0, 2500, 7)


def _boing():
    """Cartoon spring 'boing': a twangy plucked spring, wobbling as it settles."""
    d = 1.0
    t = _t(d)
    f = 180 * (1 + 0.9 * np.exp(-9 * t)) * (1 + 0.12 * np.sin(2 * np.pi * 11 * t) * np.exp(-3 * t))
    ph = 2 * np.pi * np.cumsum(f) / SR
    twang = (np.sin(ph) + 0.5 * np.sin(2 * ph) + 0.25 * np.sin(3.02 * ph)) * np.minimum(1, t / 0.004) * np.exp(-3.2 * t)
    spring = np.zeros_like(twang)  # metallic spring resonance (a short comb)
    lag = int(SR * 0.0045)
    spring[lag:] = twang[:-lag]
    x = _mix(d, (0, _st(twang + 0.45 * spring, twang - 0.2 * spring), 0.8), (0, _transient(0.7, 4, 2500, 81), 1))
    return _room(x, 0.15, 0.5)


def _cha_ching2():
    """Cash register: lever clunk, drawer sliding out, the bell 'ching', coins settling."""
    rng = np.random.default_rng(91)
    clunk = _mix(0.2, (0, _st(_lp(_noise(0.15, 92), 900) * _env(_n(0.15), 0.001, 30)), 0.9), (0, _st(_sub(80, 0.15, 25)), 0.7),
                 (0, _transient(0.9, 4, 2000, 93), 1))
    slide = _bp(_noise(0.25, 94), 600, 3000) * np.minimum(1, _t(0.25) / 0.05) * np.exp(-6 * _t(0.25))
    bell = _mix(1.6, (0, _bell(2093, 1.6, 2.2, 1.6, 6), 0.7), (0, _bell(3140, 1.4, 2.6, 1.2, 9), 0.45), (0, _bell(4186, 1.0, 3.4, 1.0), 0.25))
    coins = [(0.25 + rng.uniform(0, 0.35), _bell(rng.uniform(5200, 7600), 0.25, 18, 1.2), 0.12, rng.uniform(-0.8, 0.8)) for _ in range(10)]
    x = _mix(1.9, (0, clunk, 0.8), (0.03, _st(slide), 0.35), (0.12, bell, 1.0), (0.12, _transient(0.6, 3, 4000, 95), 1), *coins)
    return _room(x, 0.25, 1.0, 9000, 9)


SYNTH = {
    "sparkle": _sparkle, "twinkle": _twinkle, "level_up": _level_up, "coin": _coin, "success": _success,
    "double_ding": _double_ding, "bling": _bling, "magic": _magic, "tada": _tada, "party": _party,
    "applause": _applause, "swoosh_up": _swoosh_up, "swoosh_down": _swoosh_down, "bubble": _bubble,
    "heart": _heart, "reveal": _reveal, "ping": _ping, "shutter": _shutter, "click": _click, "cha_ching": _cha_ching,
    "pop": _pop, "ding": _ding, "whoosh": _whoosh2, "thwack": _thwack, "jingle": _jingle,
    "angel_ahh": _angel_ahh, "sigh_ahh": _sigh_ahh, "crowd_ooh": _crowd_ooh, "slide_up": _slide_up,
    "slide_down": _slide_down, "bass_drop": _bass_drop, "dun_dun": _dun_dun, "heartbeat": _heartbeat, "whip": _whip,
    # the old meme-library versions, rebuilt properly
    "rimshot": _rimshot, "scratch": _scratch, "gavel": _gavel, "buzzer": _buzzer, "boom": _boom, "boing": _boing,
    "cha_ching": _cha_ching2,
}

# where the "hit" is (seconds into the sound) so it lands on the beat you dropped it on
HIT = {**memesfx.HIT, "reveal": 1.25, "tada": 0.17, "swoosh_up": 0.5, "swoosh_down": 0.2, "whoosh": 0.3, "magic": 0.0,
       "cha_ching": 0.1, "coin": 0.08, "success": 0.14, "double_ding": 0.0, "thwack": 0.0, "jingle": 0.0,
       "angel_ahh": 0.0, "sigh_ahh": 0.0, "crowd_ooh": 0.0, "slide_up": 0.0, "slide_down": 0.0,
       "bass_drop": 0.0, "dun_dun": 0.0, "heartbeat": 0.0, "whip": 0.125,
       "rimshot": 0.0, "scratch": 0.0, "gavel": 0.0, "buzzer": 0.0, "boom": 0.0, "boing": 0.0, "cha_ching": 0.12}

# name, label, emoji, group
CATALOG = [
    ("sparkle", "Sparkle", "✨", "Positive"), ("twinkle", "Twinkle", "🌟", "Positive"),
    ("magic", "Magic wand", "🪄", "Positive"), ("bling", "Bling", "💎", "Positive"),
    ("success", "Success chime", "✅", "Positive"), ("double_ding", "Ding ding", "🛎️", "Positive"),
    ("level_up", "Level up", "⬆️", "Positive"), ("coin", "Coin", "🪙", "Positive"),
    ("cha_ching", "Cha-ching", "💰", "Positive"), ("tada", "Ta-da", "🎉", "Positive"),
    ("party", "Party horn", "🥳", "Positive"), ("applause", "Applause", "👏", "Positive"),
    ("heart", "Aww", "💗", "Positive"), ("reveal", "Drumroll reveal", "🥁", "Positive"),
    ("ping", "Notification", "🔔", "Positive"), ("ding", "Ding", "🔊", "Positive"),
    ("jingle", "Game-show jingle", "🎵", "Positive"),
    ("pop", "Pop", "🫧", "Transitions"), ("bubble", "Bubble", "🫧", "Transitions"),
    ("whoosh", "Whoosh", "💨", "Transitions"), ("swoosh_up", "Swoosh up", "🚀", "Transitions"),
    ("swoosh_down", "Swoosh down", "🪂", "Transitions"), ("click", "Click", "🖱️", "Transitions"),
    ("shutter", "Camera", "📸", "Transitions"), ("whip", "Whip pan", "🌀", "Transitions"),
    ("slide_up", "Slide whistle up", "📈", "Transitions"), ("slide_down", "Slide whistle down", "📉", "Transitions"),
    ("boom", "Boom", "💥", "Reactions"), ("scratch", "Record scratch", "💿", "Reactions"),
    ("buzzer", "Wrong buzzer", "❌", "Reactions"), ("boing", "Boing", "🤸", "Reactions"),
    ("gavel", "Gavel", "🔨", "Reactions"), ("thwack", "Thwack", "👊", "Reactions"), ("rimshot", "Rimshot", "🥁", "Reactions"),
    ("crickets", "Crickets", "🦗", "Reactions"), ("sad_trombone", "Sad trombone", "🎺", "Reactions"),
    ("angel_ahh", "Angel ahh", "😇", "Reactions"), ("sigh_ahh", "Relieved ahh", "😌", "Reactions"),
    ("crowd_ooh", "Crowd ooh", "😮", "Reactions"), ("dun_dun", "Dun dun duun", "😱", "Reactions"),
    ("heartbeat", "Heartbeat", "💓", "Reactions"), ("bass_drop", "Bass drop", "🔊", "Reactions"),
]
NAMES = {c[0] for c in CATALOG}


def _read_wav(p: Path) -> np.ndarray:
    with wave.open(str(p)) as w:
        raw, sw, ch = w.readframes(w.getnframes()), w.getsampwidth(), w.getnchannels()
    a = np.frombuffer(raw, dtype={2: np.int16, 4: np.int32}[sw]).astype(float) / (2 ** (8 * sw - 1))
    return a.reshape(-1, ch).mean(axis=1)


def _punch(x: np.ndarray, drive: float = 2.2) -> np.ndarray:
    """Soft saturation + peak normalize (stereo): louder, denser, still clean."""
    x = x / (np.abs(x).max() + 1e-9)
    x = np.tanh(drive * x) / np.tanh(drive)
    fade = int(SR * 0.012)
    if x.shape[1] > fade:
        x[:, -fade:] *= np.linspace(1, 0, fade)
    return 0.94 * x / (np.abs(x).max() + 1e-9)


def _trim(x: np.ndarray, floor_db: float = -52) -> np.ndarray:
    loud = np.nonzero(np.abs(x).max(axis=0) > 10 ** (floor_db / 20))[0]
    end = min(x.shape[1], (loud[-1] if len(loud) else 0) + int(SR * 0.03))
    x = x[:, :max(end, int(SR * 0.05))].copy()
    f = min(x.shape[1], int(SR * 0.03))
    x[:, -f:] *= np.linspace(1, 0, f)
    return x


def _write(p: Path, x: np.ndarray):
    x = _trim(x)
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.T.copy().tobytes())


def _from_meme(name: str) -> np.ndarray:
    """Meme Factory's comedy sounds: a click of attack, a little width and a room."""
    m = _read_wav(memesfx.sfx_file(name))
    x = _mix(len(m) / SR, (0, _st(m), 1), (0, _transient(0.25, 4, 2500), 1))  # centered; width comes from the room
    return _room(x, 0.18, 0.7)


def sound_file(name: str) -> Path:
    if name not in NAMES:
        raise KeyError(f"no sound {name}")
    out = SFX_DIR / f"{name}.v{VERSION}.wav"
    if not out.exists():
        raw = SYNTH[name]() if name in SYNTH else _from_meme(name)
        soft = ("crickets", "applause", "heart", "twinkle", "heartbeat")
        voices = ("angel_ahh", "sigh_ahh", "crowd_ooh")  # keep their gentle swell: barely any squash
        x = _punch(raw, 1.0 if name in voices else 1.5 if name in soft else 2.2)
        lvl = 20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-9)
        if lvl > -13:  # dense sounds (buzzer, scratch) would drown the voices: cap their loudness
            x = x * 10 ** ((-13 - lvl) / 20)
        _write(out, x)
    return out


def duration(name: str) -> float:
    with wave.open(str(sound_file(name))) as w:
        return w.getnframes() / w.getframerate()


_audible = {}


def audible(name: str, drop_db: float = 26) -> float:
    """How long the sound is actually heard: until its loudness (20ms windows) falls
    drop_db below its loudest moment and stays there. The quiet reverb tail after
    that is in the file but not something you notice."""
    if name not in _audible:
        a = _read_wav(sound_file(name))
        win = int(SR * 0.02)
        k = max(1, len(a) // win)
        rms = np.sqrt((a[: k * win].reshape(k, win) ** 2).mean(axis=1) + 1e-12)
        loud = np.nonzero(rms > rms.max() * 10 ** (-drop_db / 20))[0]
        _audible[name] = round(((loud[-1] + 1) * win / SR) if len(loud) else len(a) / SR, 3)
    return _audible[name]


def catalog() -> list:
    return [{"name": n, "label": lab, "emoji": e, "group": g, "hit": HIT.get(n, 0.0), "dur": audible(n), "file_dur": round(duration(n), 3)}
            for n, lab, e, g in CATALOG]


def events(parts: list, total: float) -> list:
    """[(video seconds the sound starts, name, volume)] for the takes in a video.
    parts = [(take, video t0)]. The sound's hit lands on its mark."""
    out = []
    for tk, t0 in parts:
        end = tk.get("_src_out", tk["out"])
        for c in tk.get("sfx") or []:
            at = float(c["at"])
            if not (tk["in"] <= at < end) or store.in_cut(tk, at):
                continue
            start = t0 + store.take_rel(tk, at) - HIT.get(c["name"], 0.0)
            if start < total:
                out.append((max(0.0, start), c["name"], float(c.get("vol", 0.9))))
    return out
