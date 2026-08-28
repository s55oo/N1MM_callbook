# N1MM Callbook – N1MM Logger+ Contest Callbook

> **Version:** 1.0 · Made by **S55OO** with AI assistance.

A compact always-on-top window that listens to the N1MM Logger+ external
UDP broadcast (XML, port **12060**) and automatically looks up the callsign
currently in the radio/RX1 via **[QRZCQ.com](https://www.qrzcq.com)**.
The operator name, QTH and grid square are shown under the callsign.

QRZCQ.com is a free public callbook that needs **no account and no API key** –
each callsign has a page at `https://www.qrzcq.com/call/<CALL>` whose lookup
info this app reads.

The UI follows the same design language as the **PingPong** lamp: a small
topmost Tkinter window with a colored canvas and a help icon.

---

## Screenshot

*(no screenshot yet)*

---

## 1. N1MM Logger+ setup

1. In N1MM Logger+: **File → Settings → Configurer → External Broadcast**,
   enable the reports you need (**RadioInfo** at minimum, and
   **ContactInfo** if you want the working callsign).
2. **Broadcast Address**: your subnet broadcast (e.g. `192.168.178.255`)
   so this computer sees the broadcast.
3. **Broadcast Port**: `12060` (default, do not change).
4. Make sure **Broadcast Data is enabled** on the transmitting computer.

> The app listens on all interfaces and picks the callsign out of the
> `RadioInfo` XML packet automatically.

---

## 2. Running

```
        double-click:  Callbook.bat     (from source, no console)
   or:  run:  pythonw n1mm_callbook.py  (from source, no window)
   or:  run:  n1mm_callbook.exe         (standalone executable)
```

Arguments:

```
python n1mm_callbook.py [--port 12060] [--config callbook.cfg]
```

- `--port` – UDP port (default 12060).
- `--config` – path to `callbook.cfg`.

---

## 3. Behavior

- When a `RadioInfo` packet with a callsign arrives, the window shows the
  callsign in large text and the operator details below.
- Lookups go to QRZCQ.com. Results are cached locally in
  `callbook_cache.json` to avoid repeated network fetches for the same
  callsign and to stay polite to the server.
- Cached lines are marked `(cached)`. Cache freshness is controlled by
  `cache_days` in `callbook.cfg` (default 30 days).
- If the lookup fails the window shows `lookup failed – no data`.
- The small **help icon** (top-right) opens QRZCQ.com in your browser.

---

## 4. Configuration (callbook.cfg)

```
[settings]
udp_port=12060
cache_days=30
cache_file=callbook_cache.json
```

- `callbook.cfg` and `callbook_cache.json` are read/written from the same
  folder as the executable/script.

---

## 5. Building the standalone EXE (for PCs without Python)

Requires Python + PyInstaller:

```bat
python -m pip install pyinstaller
python -m PyInstaller --onefile --windowed --name n1mm_callbook --manifest manifest.xml n1mm_callbook.py
copy /Y dist\n1mm_callbook.exe n1mm_callbook.exe
```

`manifest.xml` makes the window use modern common controls. The result is a
single `n1mm_callbook.exe` (no Python required) – copy it to the other
computers together with the (optional) `callbook.cfg`.

---

## 6. Files

```
n1mm_callbook.py   – main application (source code)
n1mm_callbook.exe  – standalone executable (built, no Python needed)
callbook.cfg       – configuration (UDP port, cache settings)
callbook_cache.json – local lookup cache (auto-created)
Callbook.bat       – source launcher (no console)
manifest.xml       – PyInstaller manifest (common controls)
n1mm_callbook.spec – PyInstaller build settings
dist\              – PyInstaller output
```
