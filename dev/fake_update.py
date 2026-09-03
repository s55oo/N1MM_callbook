# SPDX-License-Identifier: Unlicense
"""Seed a fake "newer release" so the update flow can be tested by hand.

It writes ``update_check.json`` next to Callbooker with a bogus future
tag (``v99.0``) pointing at a *real* release asset, so:

  * the title bar shows  "... v<current>   ·   update v99.0 available - click ?"
  * clicking the ? icon really downloads that exe to Callbooker.exe.new
  * the next launch's updater.apply_pending() really swaps it in

Usage:
    python dev/fake_update.py [state_dir] [asset_url]

`state_dir` defaults to the repo root (where Callbooker_cache.json lives);
point it at the folder next to Callbooker.exe on the machine under test.
Delete update_check.json (and Callbooker.exe.new) afterwards, or just wait
- the real check overwrites it within a day.
"""
import json
import os
import sys
import time

DEFAULT_ASSET = (
    "https://github.com/s55oo/N1MM_callbook/releases/download/v1.9/Callbooker.exe"
)

state_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
asset_url = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_ASSET

path = os.path.join(state_dir, "update_check.json")
with open(path, "w", encoding="utf-8") as fh:
    json.dump({"checked": time.time(), "latest_tag": "v99.0",
               "asset_url": asset_url}, fh)

print("wrote", path)
print("  latest_tag = v99.0")
print("  asset_url  =", asset_url)
print("\nStart Callbooker -> title bar should offer 'update v99.0'.")
print("Click the ? icon -> it downloads Callbooker.exe.new next to the exe.")
print("Restart Callbooker -> apply_pending() swaps it in.")
print("\nCleanup:  del", path, " and any Callbooker.exe.new")
