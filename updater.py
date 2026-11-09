# SPDX-License-Identifier: Unlicense
"""Optional GitHub-release update check for Callbooker.

On start-up Callbooker asks GitHub, at most every 6 hours, whether a newer
release is out (``update_check=no`` in the .cfg turns this off). If so the
footer shows a clickable ``Callbooker vX.Y available`` nudge:

* **Frozen exe** - the release's ``Callbooker.exe`` is downloaded next to
  the running one as ``Callbooker.exe.new`` (automatically, or by clicking
  the nudge when ``update_auto=no``) and checked against the SHA-256 GitHub
  publishes for the asset. A running ``.exe`` can't be overwritten, but it
  can be renamed, so the *next* launch (``apply_pending``) renames the old
  exe to ``Callbooker_<its version>.exe`` (kept as a fallback), moves the
  new one into place and relaunches - the user just restarts Callbooker
  once.
* **From source** - clicking it opens the releases page in the browser
  (update with ``git pull``).

Pure standard library. Network failures are swallowed - a broken check
never affects the app.
"""

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request

REPO = "s55oo/N1MM_callbook"
RELEASES_PAGE = "https://github.com/s55oo/N1MM_callbook/releases/"
API_LATEST = "https://api.github.com/repos/{}/releases/latest".format(REPO)
ASSET_NAME = "Callbooker.exe"
CHECK_INTERVAL = 6 * 3600       # seconds between GitHub queries
MIN_EXE_BYTES = 2_000_000       # a sanity floor for the downloaded exe
_UA = "Callbooker-updater (+https://github.com/{})".format(REPO)


def version_tuple(s):
    """``"v1.10"`` -> ``(1, 10)``; stops at the first non-numeric part;
    unparseable -> ``(0,)`` so it always compares as older."""
    out = []
    for part in str(s or "").strip().lstrip("vV").split("."):
        if not part.isdigit():
            break
        out.append(int(part))
    return tuple(out) or (0,)


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def exe_path():
    return sys.executable if is_frozen() else os.path.abspath(sys.argv[0])


# -- the periodic check --------------------------------------------------------

def _state_path(state_dir):
    return os.path.join(state_dir, "update_check.json")


def _load_state(state_dir):
    try:
        with open(_state_path(state_dir), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state_dir, data):
    try:
        tmp = _state_path(state_dir) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, _state_path(state_dir))
    except OSError:
        pass


def _fetch_latest():
    """(tag, asset_url, sha256) for the repo's latest release, or None on
    any error. ``asset_url`` is '' when the release has no Callbooker.exe;
    ``sha256`` is the hex digest GitHub reports for it ('' if unknown)."""
    try:
        req = urllib.request.Request(API_LATEST, headers={
            "User-Agent": _UA, "Accept": "application/vnd.github+json",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
    except Exception:
        return None
    tag = (data.get("tag_name") or "").strip()
    if not tag:
        return None
    asset_url = ""
    digest = ""
    for asset in data.get("assets") or []:
        if asset.get("name") == ASSET_NAME:
            asset_url = asset.get("browser_download_url") or ""
            d = str(asset.get("digest") or "")
            if d.lower().startswith("sha256:"):
                digest = d[7:].strip().lower()
            break
    return tag, asset_url, digest


def check(current_version, state_dir, force=False):
    """Return ``(tag, asset_url)`` when GitHub's latest release is newer
    than *current_version*, else None. Hits the network at most once per
    ``CHECK_INTERVAL`` (``force=True`` always asks - the manual button); the last result is cached in ``update_check.json``
    next to the other state files."""
    st = _load_state(state_dir)
    now = time.time()
    tag = st.get("latest_tag")
    asset_url = st.get("asset_url", "")
    if force or not tag or (now - st.get("checked", 0)) > CHECK_INTERVAL:
        fetched = _fetch_latest()
        if fetched:
            tag, asset_url = fetched[0], fetched[1]
            digest = fetched[2] if len(fetched) > 2 else ""
            _save_state(state_dir, {
                "checked": now, "latest_tag": tag, "asset_url": asset_url,
                "digest": digest, "failed": False,
            })
        else:
            # network failure: keep the old answer, retry in ~1 h not hours
            st["checked"] = now - CHECK_INTERVAL + 3600
            st["failed"] = True
            _save_state(state_dir, st)
    if tag and version_tuple(tag) > version_tuple(current_version):
        return tag, asset_url
    return None


def status(state_dir):
    """What the last check found, for the idle footer: ``(latest_tag,
    checked_epoch, failed)``; ``latest_tag`` is '' before the first check."""
    st = _load_state(state_dir)
    return (str(st.get("latest_tag") or ""), float(st.get("checked") or 0),
            bool(st.get("failed")))


def cached_digest(state_dir):
    """SHA-256 (hex) GitHub reported for the cached latest release's exe,
    or '' when unknown."""
    return str(_load_state(state_dir).get("digest") or "")


# -- download + apply -----------------------------------------------------

def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(asset_url, dest, sha256=""):
    """Fetch *asset_url* to ``dest + ".part"`` then atomically rename it to
    *dest*. Returns True on success. A suspiciously small file is
    rejected, and so is one whose SHA-256 differs from *sha256* (when
    given)."""
    if not asset_url:
        return False
    part = dest + ".part"
    try:
        req = urllib.request.Request(asset_url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=120) as resp:
            with open(part, "wb") as out:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    out.write(chunk)
        if os.path.getsize(part) < MIN_EXE_BYTES:
            raise ValueError("downloaded file too small")
        if sha256 and _sha256_file(part) != sha256.strip().lower():
            raise ValueError("SHA-256 mismatch")
        os.replace(part, dest)
        return True
    except Exception:
        try:
            if os.path.exists(part):
                os.remove(part)
        except OSError:
            pass
        return False


def _swap(exe, new, old):
    """Rename *exe* -> *old*, *new* -> *exe*. Returns True on success and
    rolls back a half-done swap. A running .exe can be renamed on Windows
    even though it can't be deleted or overwritten."""
    try:
        os.replace(exe, old)
    except OSError:
        return False
    try:
        os.replace(new, exe)
    except OSError:
        try:
            os.replace(old, exe)   # roll back
        except OSError:
            pass
        return False
    return True


def backup_name(exe, version):
    """Where the outgoing exe is kept: ``Callbooker_1.12.exe`` next to it
    (``_2``, ``_3`` ... if that name is taken, so an earlier backup is never
    overwritten). Without a *version* the old ``<exe>.old`` name is used."""
    version = str(version or "").strip().lstrip("vV")
    if not version:
        return exe + ".old"
    base, ext = os.path.splitext(exe)
    cand = "{}_{}{}".format(base, version, ext)
    n = 2
    while os.path.exists(cand):
        cand = "{}_{}_{}{}".format(base, version, n, ext)
        n += 1
    return cand


def apply_pending(version=""):
    """Run once at start-up, before the GUI. If ``Callbooker.exe.new`` is
    waiting next to the running exe, swap it in and relaunch; the outgoing
    exe is kept as ``Callbooker_<version>.exe`` (*version* = the running
    build's version). Returns True when it relaunched (the caller must
    then exit immediately)."""
    if not is_frozen():
        return False
    exe = sys.executable
    new = exe + ".new"
    legacy = exe + ".old"
    if os.path.exists(legacy):       # tidy the pre-1.14 update's leftover
        try:
            os.remove(legacy)
        except OSError:
            pass
    if not os.path.exists(new):
        return False
    old = backup_name(exe, version)
    if not _swap(exe, new, old):
        return False
    try:
        # Callbooker.exe is a windowed (no-console) build; relaunch it with
        # no std handles and no new console so nothing flashes.
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # A --onefile exe that relaunches itself must tell PyInstaller the
        # child is a fresh app: otherwise it inherits our _MEI temp dir,
        # which our own bootloader deletes as we exit - the new instance
        # then dies intermittently (about half the time in testing).
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
        subprocess.Popen(
            [exe] + sys.argv[1:], close_fds=True, creationflags=flags,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env=env,
        )
    except OSError:
        return False
    return True
