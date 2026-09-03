# SPDX-License-Identifier: Unlicense
"""Optional GitHub-release update check for Callbooker.

On start-up Callbooker asks GitHub, at most once a day, whether a newer
release is out (``update_check=no`` in the .cfg turns this off). If so the
footer shows a clickable ``Callbooker vX.Y available`` nudge:

* **Frozen exe** - clicking it downloads the release's ``Callbooker.exe``
  next to the running one as ``Callbooker.exe.new``. A running ``.exe``
  can't be overwritten, but it can be renamed, so the *next* launch
  (``apply_pending``) renames the old exe aside, moves the new one into
  place and relaunches - the user just restarts Callbooker once.
* **From source** - clicking it opens the releases page in the browser
  (update with ``git pull``).

Pure standard library. Network failures are swallowed - a broken check
never affects the app.
"""

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
CHECK_INTERVAL = 86400          # seconds between GitHub queries
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


# -- the daily check --------------------------------------------------------

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
    """(tag, asset_url) for the repo's latest release, or None on any
    error. ``asset_url`` is '' when the release has no Callbooker.exe."""
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
    for asset in data.get("assets") or []:
        if asset.get("name") == ASSET_NAME:
            asset_url = asset.get("browser_download_url") or ""
            break
    return tag, asset_url


def check(current_version, state_dir):
    """Return ``(tag, asset_url)`` when GitHub's latest release is newer
    than *current_version*, else None. Hits the network at most once per
    ``CHECK_INTERVAL``; the last result is cached in ``update_check.json``
    next to the other state files."""
    st = _load_state(state_dir)
    now = time.time()
    tag = st.get("latest_tag")
    asset_url = st.get("asset_url", "")
    if not tag or (now - st.get("checked", 0)) > CHECK_INTERVAL:
        fetched = _fetch_latest()
        if fetched:
            tag, asset_url = fetched
            _save_state(state_dir, {
                "checked": now, "latest_tag": tag, "asset_url": asset_url,
            })
        else:
            # network failure: keep the old answer, retry in ~1 h not a day
            st["checked"] = now - CHECK_INTERVAL + 3600
            _save_state(state_dir, st)
    if tag and version_tuple(tag) > version_tuple(current_version):
        return tag, asset_url
    return None


# -- download + apply -----------------------------------------------------

def download(asset_url, dest):
    """Fetch *asset_url* to ``dest + ".part"`` then atomically rename it to
    *dest*. Returns True on success. A suspiciously small file is
    rejected."""
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


def apply_pending():
    """Run once at start-up, before the GUI. If ``Callbooker.exe.new`` is
    waiting next to the running exe, swap it in and relaunch. Returns True
    when it relaunched (the caller must then exit immediately)."""
    if not is_frozen():
        return False
    exe = sys.executable
    new = exe + ".new"
    old = exe + ".old"
    if os.path.exists(old):          # tidy the previous update's leftover
        try:
            os.remove(old)
        except OSError:
            pass
    if not os.path.exists(new):
        return False
    if not _swap(exe, new, old):
        return False
    try:
        # Callbooker.exe is a windowed (no-console) build; relaunch it with
        # no std handles and no new console so nothing flashes.
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [exe] + sys.argv[1:], close_fds=True, creationflags=flags,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return True
