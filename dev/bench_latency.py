# SPDX-License-Identifier: Unlicense
"""Measure callbook lookup latency: per source and end to end.

QRZ credentials, if you want that source measured, are read from
`Callbooker.cfg` (same as the app) - nothing is hard-coded here.

Run:  python dev/bench_latency.py
"""
import functools
import os
import statistics
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import n1mm_callbook as cb  # noqa: E402

CALLS = ["W1AW", "K3LR", "K1TTT", "W3LPL", "K1LZ", "S55OO", "S56A", "K9LP"]
REPEATS = 3

cfg = cb.load_config(os.path.join(ROOT, "Callbooker.cfg"))
QRZ_USER = cfg.get("qrz_username", "")
QRZ_PASS = cfg.get("qrz_password", "")


def stat(label, xs):
    xs = [x * 1000 for x in xs]
    print(f"  {label:24} median {statistics.median(xs):6.0f}  "
          f"mean {statistics.mean(xs):6.0f}  min {min(xs):6.0f}  "
          f"max {max(xs):6.0f}  ms")


def time_call(fn, call):
    t0 = time.perf_counter()
    try:
        fn(call)
    except Exception:
        pass
    return time.perf_counter() - t0


SOURCES = [
    ("qrz", functools.partial(cb.qrz_lookup, username=QRZ_USER, password=QRZ_PASS)),
    ("qrzcq", cb.qrzcq_lookup),
    ("hamqth", cb.hamqth_lookup),
]
if not (QRZ_USER and QRZ_PASS):
    print("(no qrz_username/qrz_password in Callbooker.cfg - QRZ = public page)\n")

# warm the connection pool and the QRZ session
for _, fn in SOURCES:
    fn("W1AW")

print(f"calls: {CALLS}   repeats: {REPEATS}\n")

for name, fn in SOURCES:
    times = []
    for call in CALLS:
        times.append(statistics.median(time_call(fn, call) for _ in range(REPEATS)))
    print(f"=== {name} ===")
    stat("warm lookup", times)
    print()

# end to end: all sources in parallel, like the app
print("=== end to end (all sources in parallel) ===")
wall = []
for call in CALLS:
    ths = [threading.Thread(target=time_call, args=(fn, call)) for _, fn in SOURCES]
    t0 = time.perf_counter()
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    dt = time.perf_counter() - t0
    wall.append(dt)
    print(f"  {call:8} {dt*1000:5.0f} ms")
stat("all-slots wall", wall)
