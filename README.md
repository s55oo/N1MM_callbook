# N1MM Callbook – N1MM Logger+ Contest Callbook

> **Version:** 1.3 · Made by **S55OO** with AI assistance.

A compact always-on-top window that listens to the N1MM Logger+ external
UDP broadcast (XML, port **12060**) and automatically looks up the callsign
you are working via **[QRZCQ.com](https://www.qrzcq.com)**. The window
shows the worked station's **name – US state** in the main area, and
the **callsign** in the footer.

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

1. In N1MM Logger+: **File → Settings → Configurer → Broadcast Data**
   (a.k.a. External Broadcast), enable:
   - **External Callsign Lookup** – sends a `LookupInfo` packet after you
     type a callsign and press **Space** (i.e. as you move to the exchange
     field). This is the primary trigger for the callbook.
   - **Contacts** – sends a `ContactInfo` packet when a QSO is logged.
2. Set the **IP:Port** next to them to your PC's address (or the subnet
   broadcast) and port **12060**.
3. Make sure **Broadcast Data is enabled** on the transmitting computer.

> The app listens on all interfaces and picks the worked callsign out of
> the `LookupInfo`/`ContactInfo` packet automatically. `RadioInfo` only
> carries the local operator's own call and is deliberately ignored.

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

- When a `LookupInfo` (type a call + press Space) or `ContactInfo` (QSO
  logged) packet arrives, the window shows the worked callsign in the
  footer and looks up the operator on QRZCQ.com.
- The main area shows the operator's **name – US state** (state blank for
  non-US calls; the font shrinks automatically for long names).
- **Local computer only:** the app only reacts to packets sent from *this*
  PC (identified by its local interface IPs). Broadcasts from other
  stations on the network are ignored, so only the local operator's
  callsign triggers a lookup.
- Lookups are cached locally in `callbook_cache.json` to avoid repeated
  network fetches for the same callsign and to stay polite to the server.
- Cache freshness is controlled by `cache_days` in `callbook.cfg`
  (default 30 days).
- If the lookup fails the main area shows `lookup failed`; if a callsign
  has no entry it shows `no data`.
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
