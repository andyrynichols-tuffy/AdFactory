"""Version history for the apps (git, in this folder), so any update can be rolled back.

- Code (the apps themselves) is saved as a version shortly after it changes and settles,
  one version per change with the changed files in its name.
- Your content (posts in projects/, Ad Factory shoots in ads/) is saved too, at most every
  30 minutes, so its history exists without a version for every autosave.
- Rolling back only ever touches CODE: it puts the apps' files back the way they were at
  that version (as a new version, so the rollback itself can be undone). Posts and shoots
  are never rolled back from here. Ad Factory then restarts itself.
- Backup: every 10 minutes, in the background (a slow or offline network never holds
  anything up), Ad Factory syncs with the private GitHub repo (remote "origin"): first it brings
  in what's new there (a pull request merged on GitHub, work pushed from another computer),
  then it pushes this PC's versions. GitHub's changes are merged only when a trial merge
  (which touches no files) shows they don't clash with this PC's, and none of the files they
  change has edits here that aren't saved as a version yet. Otherwise nothing is touched,
  and it says why (logs/backup.log, and the window's backup status) until it's sorted. Every outcome that isn't "up to
  date" goes in %USERPROFILE%\\MemeSupercutData\\logs\\backup.log."""
import os
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CODE = ["adcut", "adkit", "adapp", "adeditor", "ios", "tools", "fonts", "shared", "docs",
        "CLAUDE.md", "README.md", "requirements.txt", ".gitignore", ".claude/launch.json", "config.json",
        "start-ad-editor.bat", "start-ad-editor-background.vbs"]
CONTENT = ["ads"]
SETTLE = 20           # seconds a code change must sit still before it's saved (no half-edits)
CONTENT_EVERY = 1800  # seconds between content snapshots
_last_content = 0.0
PUSH_EVERY = 600      # seconds between backups to GitHub
NETWORK_TIMEOUT = 120  # seconds a fetch or push may take before it counts as failed
LOG = Path.home() / "MemeSupercutData" / "logs" / "backup-adfactory.log"
_last_push = 0.0
_pushing = threading.Lock()
_lock = threading.RLock()  # commits, merges and rollbacks take turns (they share git's index)
_status = {"state": "unknown", "message": "", "at": 0.0, "ok_at": 0.0}  # the last backup, for the window


def git(*args, check=False):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", creationflags=NO_WINDOW)
    if check and r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip()[-400:])
    return r.stdout


def _run(*args, timeout=None):
    """git for the backup: (exit code, output, errors). It never asks for a password (it would
    wait forever with no window), and a network hang counts as a failure."""
    try:
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", creationflags=NO_WINDOW, timeout=timeout,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except subprocess.TimeoutExpired:
        return 124, "", f"git {args[0]} took longer than {timeout} s"
    return r.returncode, r.stdout, r.stderr


def _existing(paths):
    return [p for p in paths if (ROOT / p).exists()]


def _changed(paths):
    out = git("status", "--porcelain", "--untracked-files=all", "--", *_existing(paths))
    return [line[3:].strip().strip('"') for line in out.splitlines() if line.strip()]


def _settled(files):
    newest = 0.0
    for f in files:
        try:
            newest = max(newest, (ROOT / f).stat().st_mtime)
        except OSError:
            pass
    return time.time() - newest > SETTLE


def _commit(paths, message):
    with _lock:
        git("add", "-A", "--", *_existing(paths), check=True)
        if not git("diff", "--cached", "--name-only").strip():
            return None
        git("commit", "-q", "-m", message, check=True)
        return git("rev-parse", "--short", "HEAD").strip()


def _summary(files, limit=4):
    names = [Path(f).as_posix() for f in files]
    return ", ".join(names[:limit]) + (f" +{len(names) - limit} more" if len(names) > limit else "")


def snapshot():
    """Called every few seconds by the supervisor: save settled changes as versions."""
    global _last_content
    code = _changed(CODE)
    if code and _settled(code):
        _commit(CODE, f"Update: {_summary(code)}")
    if time.time() - _last_content > CONTENT_EVERY:
        content = _changed(CONTENT)
        if content and _settled(content):
            n_posts = len({f.split("/")[1] for f in content if f.startswith("projects/") and "/" in f[9:]})
            n_shoots = len({f.split("/")[1] for f in content if f.startswith("ads/") and "/" in f[4:]})
            bits = [f"{n_posts} post{'s' * (n_posts != 1)}" if n_posts else "", f"{n_shoots} shoot{'s' * (n_shoots != 1)}" if n_shoots else ""]
            _commit(CONTENT, "Content: " + (" · ".join(b for b in bits if b) or _summary(content)))
        _last_content = time.time()
    _backup()


def _backup():
    """Sync with GitHub (private repo) every PUSH_EVERY seconds, in the background; never waits on it."""
    global _last_push
    if time.time() - _last_push < PUSH_EVERY or _pushing.locked():
        return
    _last_push = time.time()
    if not git("remote").strip():
        return
    threading.Thread(target=sync, daemon=True, name="backup").start()


def sync():
    """Bring in GitHub's new versions when that's safe, then push this PC's."""
    with _pushing:
        code, _, err = _run("fetch", "-q", "origin", timeout=NETWORK_TIMEOUT)
        if code:
            return _report("failing", f"Couldn't reach GitHub: {_last_line(err)}")
        behind = _count("HEAD..@{u}")
        if behind is None:
            return _report("failing", "This copy isn't linked to a branch on GitHub, so there's nowhere to back up to.")
        incoming = []
        if behind:
            incoming, problem = _bring_in()
            if problem:
                return _report(*problem)
        ahead = _count("@{u}..HEAD") or 0
        if ahead:
            code, _, err = _run("push", "-q", "origin", "HEAD", timeout=NETWORK_TIMEOUT)
            if code:
                return _report("failing", f"GitHub didn't take this PC's versions: {_last_line(err)}")
        done = [f"Brought in {_summary(incoming)} from GitHub" if incoming else "",
                f"sent {ahead} version{'s' * (ahead != 1)} to GitHub" if ahead else ""]
        message = "; ".join(d for d in done if d) or "Up to date with GitHub"
        if any(f.startswith("adapp/") for f in incoming):
            message += ". The Ad Factory app itself changed too: quit it from the tray and start it again to use it"
        _report("ok", message[0].upper() + message[1:] + ".", log=bool(incoming or ahead))


def _bring_in():
    """Merge what's new on GitHub into this PC's versions: (files that came in, None), or
    ([], (state, why)) when it isn't safe, in which case nothing has been touched."""
    incoming = [f for f in _run("diff", "--name-only", "HEAD...@{u}")[1].splitlines() if f.strip()]
    # a trial merge in git's object store only: it shows clashes without writing any files
    code, out, _ = _run("merge-tree", "--write-tree", "--name-only", "--no-messages", "HEAD", "@{u}")
    if code == 1:
        clash = [f for f in out.splitlines()[1:] if f.strip()]
        return [], ("failing", f"GitHub has changes that clash with this PC's ({_summary(clash)}). Nothing was merged, "
                               "and backups wait until someone merges them by hand (git pull origin master).")
    if code:
        return [], ("failing", "This PC's Git is too old to check GitHub's changes for clashes, so they weren't merged. "
                               "Update Git for Windows (2.38 or newer).")
    with _lock:
        out = git("status", "--porcelain", "--untracked-files=all")
        unsaved = {line[3:].strip().strip('"') for line in out.splitlines() if line.strip()}
        busy = [f for f in incoming if f in unsaved]
        if busy:
            return [], ("waiting", f"GitHub changed files that have edits here not saved as a version yet "
                                   f"({_summary(busy)}). Trying again in {PUSH_EVERY // 60} minutes.")
        code, _, err = _run("merge", "--no-edit", "-m", f"Update from GitHub: {_summary(incoming)}", "@{u}")
        if code:
            if (ROOT / ".git" / "MERGE_HEAD").exists():
                _run("merge", "--abort")
            return [], ("failing", f"Couldn't merge GitHub's changes: {_last_line(err)}")
    return incoming, None


def _count(span):
    code, out, _ = _run("rev-list", "--count", span)
    return int(out.strip()) if code == 0 and out.strip().isdigit() else None


def _last_line(text):
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1][:300] if lines else "no details"


def _report(state, message, log=True):
    now = time.time()
    _status.update(state=state, message=message, at=now)
    if state == "ok":
        _status["ok_at"] = now
    if log or state != "ok":
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with LOG.open("a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {state}: {message}\n")
        except OSError:
            pass


def backup_status():
    """The last backup, for the Ad Factory window: state ok / waiting / failing / unknown."""
    return dict(_status)


def history(n=40):
    """Recent CODE versions, newest first."""
    out = git("log", f"-{n}", "--date=format:%Y-%m-%d %H:%M", "--format=%h%x1f%ad%x1f%s", "--", *_existing(CODE))
    rows = []
    for line in out.splitlines():
        sha, when, msg = (line.split("\x1f") + ["", ""])[:3]
        rows.append({"sha": sha, "when": when, "message": msg})
    if rows:
        rows[0]["current"] = True
    return rows


def rollback(sha):
    """Put the apps' code back to version `sha` (as a new version; content untouched)."""
    if not git("cat-file", "-t", sha).strip():
        raise ValueError(f"no version {sha}")
    with _lock:
        _commit(CODE, "Saved before rollback")  # nothing unsaved gets lost
        msg = git("log", "-1", "--format=%s", sha).strip()
        # the app shell (adapp/) never rolls itself back (it's what does the rolling back), and paths that
        # didn't exist yet in that version are left alone rather than deleted.
        paths = [p for p in _existing(CODE) if p != "adapp" and git("ls-tree", sha, "--", p).strip()]
        git("restore", f"--source={sha}", "--staged", "--worktree", "--", *paths, check=True)
        git("commit", "-q", "-m", f"Roll back to {sha} ({msg})", check=True)
        return git("rev-parse", "--short", "HEAD").strip()
