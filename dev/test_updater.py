# SPDX-License-Identifier: Unlicense
"""Headless checks for updater.py - no network, no real exe."""

import io
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import updater as up  # noqa: E402


def check(label, got, want):
    ok = "ok  " if got == want else "FAIL"
    print(f"  [{ok}] {label:52} -> {got!r}")
    if got != want:
        print(f"         expected {want!r}")
    return got == want


def version_tests():
    ok = True
    ok &= check("v-prefix stripped", up.version_tuple("v1.9"), (1, 9))
    ok &= check("multi-digit part", up.version_tuple("1.10"), (1, 10))
    ok &= check("1.10 > 1.9", up.version_tuple("1.10") > up.version_tuple("1.9"), True)
    ok &= check("1.9 not > 1.9", up.version_tuple("v1.9") > up.version_tuple("1.9"), False)
    ok &= check("trailing junk stops parse", up.version_tuple("1.9-rc1"), (1,))
    ok &= check("empty -> (0,)", up.version_tuple(""), (0,))
    return ok


def check_throttle_tests():
    ok = True
    d = tempfile.mkdtemp()
    calls = []
    real_fetch = up._fetch_latest
    up._fetch_latest = lambda: calls.append(1) or ("v2.0", "http://x/Callbooker.exe")
    try:
        r = up.check("1.9", d)
        ok &= check("newer release -> (tag, asset_url)",
                    r, ("v2.0", "http://x/Callbooker.exe"))
        ok &= check("first call hits the network", len(calls), 1)
        r2 = up.check("1.9", d)
        ok &= check("second call within a day is served from cache",
                    (r2, len(calls)), (("v2.0", "http://x/Callbooker.exe"), 1))

        up._fetch_latest = lambda: calls.append(1) or ("v1.9", "")
        # force a re-check by ageing the state file
        sp = up._state_path(d)
        st = up._load_state(d)
        st["checked"] = time.time() - up.CHECK_INTERVAL - 1
        up._save_state(d, st)
        r3 = up.check("1.9", d)
        ok &= check("same version -> None", r3, None)
        ok &= check("older/equal release does not offer an update",
                    up.check("2.5", d), None)

        # network failure keeps the last good answer and retries sooner
        up._fetch_latest = lambda: None
        st = up._load_state(d)
        st["checked"] = time.time() - up.CHECK_INTERVAL - 1
        st["latest_tag"] = "v3.0"
        up._save_state(d, st)
        ok &= check("fetch failure -> falls back to the cached tag",
                    up.check("1.9", d), ("v3.0", st.get("asset_url", "")))
        ok &= check("fetch failure shortens the retry gap",
                    (time.time() - up._load_state(d)["checked"]) < up.CHECK_INTERVAL,
                    True)
    finally:
        up._fetch_latest = real_fetch
    return ok


def download_tests():
    ok = True
    import urllib.request

    class FakeResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()

    payload = {"url": None}
    big = b"MZ" + b"\0" * (up.MIN_EXE_BYTES + 10)
    small = b"MZ" + b"\0" * 100

    def fake_urlopen(req, timeout=0):
        return FakeResp(payload["blob"])

    real = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        dest = tempfile.mktemp(suffix=".exe.new")
        payload["blob"] = big
        ok &= check("download writes the file", up.download("http://x", dest), True)
        ok &= check("downloaded bytes land at dest",
                    os.path.exists(dest) and os.path.getsize(dest) == len(big), True)
        os.remove(dest)

        payload["blob"] = small
        ok &= check("a too-small download is rejected",
                    up.download("http://x", dest), False)
        ok &= check("rejected download leaves nothing behind",
                    os.path.exists(dest) or os.path.exists(dest + ".part"), False)

        ok &= check("empty asset_url -> False", up.download("", dest), False)
    finally:
        urllib.request.urlopen = real
    return ok


def swap_tests():
    ok = True
    d = tempfile.mkdtemp()
    exe = os.path.join(d, "Callbooker.exe")
    new = exe + ".new"
    old = exe + ".old"
    open(exe, "wb").write(b"OLD")
    open(new, "wb").write(b"NEW")
    ok &= check("_swap returns True", up._swap(exe, new, old), True)
    ok &= check("exe now holds the new bytes", open(exe, "rb").read(), b"NEW")
    ok &= check("old exe kept aside", open(old, "rb").read(), b"OLD")
    ok &= check(".new consumed", os.path.exists(new), False)

    # rollback when the second rename fails (.new missing)
    open(exe, "wb").write(b"OLD2")
    ok &= check("_swap with no .new -> False", up._swap(exe, exe + ".new", old), False)
    ok &= check("rolled back - exe intact", open(exe, "rb").read(), b"OLD2")
    return ok


def main():
    ok = True
    print("version_tuple")
    ok &= version_tests()
    print("check() + throttle")
    ok &= check_throttle_tests()
    print("download()")
    ok &= download_tests()
    print("_swap()")
    ok &= swap_tests()
    print("\n" + ("ALL PASS" if ok else "SOME FAILED"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
