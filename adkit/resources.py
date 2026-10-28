"""How the apps on this PC share it with PlayOn (Meme Factory, Ad Factory, PlayOn Queue, CLI).

PlayOn Home records in real time on this PC: anything that starves it while it captures
leaves a truncated, "broken" recording (seen 2026-10-20 when indexing and renders ran
during a recording). The rules, so our work still goes as fast as the PC allows:

1. CPU: every app process runs at a lowered priority class: below normal normally, idle
   while PlayOn is recording. Windows gives PlayOn (and the person at the keyboard) the
   processor first and our work soaks up everything left over, so when the PC is free
   it's full speed. Child processes (ffmpeg, ffprobe) inherit the class. A watcher thread
   re-checks PlayOn every few seconds and moves the class up/down. Measured 2026-10-21:
   five renders at idle priority during a recording, the recording held 1.0x real time.
2. GPU (Whisper transcription on CUDA) is the heaviest job and its GPU use can't be
   deprioritised, so it pauses while PlayOn records (`yield_to_playon()` between pieces of
   work) and only one transcription runs at a time across all apps (`gpu_slot()`).
   Renders encode on the card's NVENC chip, which is separate from the CUDA cores; they
   just follow rule 1.
3. Parallelism: `workers()` renders that many video segments at once: several when PlayOn
   is idle, one while it records.

Standard library only (the PlayOn Queue app imports it too)."""
import contextlib
import ctypes
import os
import sqlite3
import threading
import time
from pathlib import Path

RECORDING_DB = Path(r"C:\ProgramData\MediaMall\Recording\recording.db")
CHECK_EVERY = 5  # seconds between PlayOn checks
NORMAL, BELOW_NORMAL, IDLE = 0x20, 0x4000, 0x40
LOCK_FILE = Path.home() / "MemeSupercutData" / "gpu.lock"

_state = {"t": 0.0, "recording": False, "queued": 0}
_state_lock = threading.Lock()
_gpu_local = threading.Lock()
_installed = False


def playon():
    """{'recording': bool, 'queued': n} from PlayOn's queue (read-only, cached a few seconds)."""
    with _state_lock:
        if time.time() - _state["t"] < CHECK_EVERY:
            return dict(_state)
        rec, queued = False, 0
        try:
            con = sqlite3.connect(f"file:{RECORDING_DB.as_posix()}?mode=ro", uri=True, timeout=2)
            try:
                rows = dict(con.execute("SELECT Status, COUNT(*) FROM RecordQueueItems "
                                        "WHERE Status IN (0, 1) GROUP BY Status").fetchall())
                paused = (con.execute("SELECT Value FROM Settings WHERE Key='QueueState'").fetchone() or ["0"])[0] == "1"
            finally:
                con.close()
            rec, queued = bool(rows.get(1)), 0 if paused else rows.get(0, 0)
        except (sqlite3.Error, OSError):
            pass  # no PlayOn on this PC: nothing to protect
        _state.update(t=time.time(), recording=rec, queued=queued)
        return dict(_state)


def recording() -> bool:
    return playon()["recording"]


def _kernel32():
    # Declare the types: a process handle is 64-bit, and ctypes' default int would truncate it
    # (the call then fails silently and nothing gets deprioritised).
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.SetPriorityClass.restype = wintypes.BOOL
    k.GetPriorityClass.argtypes = [wintypes.HANDLE]
    k.GetPriorityClass.restype = wintypes.DWORD
    return k


def _set_priority(cls: int):
    if os.name == "nt":
        k = _kernel32()
        if not k.SetPriorityClass(k.GetCurrentProcess(), cls):
            print("resources: couldn't lower process priority, error", ctypes.get_last_error())


def priority() -> int:
    """This process's current priority class (for checks)."""
    k = _kernel32()
    return k.GetPriorityClass(k.GetCurrentProcess()) if os.name == "nt" else NORMAL


def install(watch: bool = True):
    """Call once at startup in every app/CLI process: lowered priority now, and (watch=True)
    a background thread that drops to idle whenever PlayOn starts recording."""
    global _installed
    if _installed:
        return
    _installed = True
    _set_priority(IDLE if recording() else BELOW_NORMAL)
    if watch:
        def loop():
            last = None
            while True:
                cls = IDLE if recording() else BELOW_NORMAL
                if cls != last:
                    _set_priority(cls)
                    last = cls
                time.sleep(CHECK_EVERY)
        threading.Thread(target=loop, daemon=True, name="resources").start()


def workers() -> int:
    """How many video segments to render at once (NVENC sessions + CPU filters)."""
    if recording():
        return 1
    return max(1, min(3, (os.cpu_count() or 4) // 6))


def yield_to_playon(say=None):
    """Block while PlayOn is recording. Call between pieces of GPU-heavy work."""
    told = False
    while recording():
        if say and not told:
            say("paused: PlayOn is recording (resumes automatically)")
            told = True
        time.sleep(CHECK_EVERY * 2)


@contextlib.contextmanager
def gpu_slot(say=None):
    """One GPU-heavy job at a time across every app on the PC (a lock file), and never
    while PlayOn records."""
    with _gpu_local:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        fh = open(LOCK_FILE, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                waited = False
                while True:
                    try:
                        fh.seek(0)
                        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if say and not waited:
                            say("waiting: another app is using the GPU")
                            waited = True
                        time.sleep(3)
            yield_to_playon(say)
            yield
        finally:
            if os.name == "nt":
                import msvcrt
                with contextlib.suppress(OSError):
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            fh.close()
