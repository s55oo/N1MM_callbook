"""N1MM Logger+ VHF Locator lookup.

A variant of the callbook app that shows the QRA/maidenhead locator
(e.g. JN76JG) of the worked station instead of the operator name. Sends
the same N1MM UDP packets through the exact same QRZCQ.com parsing, with
HamQTH.com and the QRZ.com public page as fallback locator sources. The
paid QRZ.com XML service is added as the FIRST source when credentials
are configured (one XML request, so it usually answers first).

QRZ needs a paid XML subscription (https://www.qrz.com/page/xml_data.html);
set qrz_username/qrz_password in n1mm_VHFcallbook.cfg to enable it.

Lookups are cached locally in n1mm_VHFcallbook_cache.json to stay polite
to the servers.

Made by S55OO with AI assistance.

Version: 1.6

Usage:
    python n1mm_VHFcallbook.py [--port 12060] [--config n1mm_VHFcallbook.cfg]
"""

__version__ = "1.6"

import argparse
import os
import sys
import tkinter as tk

import n1mm_callbook as cb

CONFIG_NAME = "n1mm_VHFcallbook.cfg"
CACHE_NAME = "n1mm_VHFcallbook_cache.json"


class VHFApp(cb.CallbookApp):
    APP_TITLE = "N1MM VHF Callbook"
    # Show all three locator values side by side (e.g. "JN76HD JN76HD JN76HD")
    # so a wrong one stands out; each source contributes its own value.
    FIELD = "grid"
    SHOW_NAME = False
    # QRZCQ first, then HamQTH's Grid: row, then the locator computed from
    # the coordinates on the public QRZ.com page. The paid QRZ XML service
    # is appended automatically when credentials are configured.
    LOOKUP_CHAIN = (cb.qrzcq_lookup, cb.hamqth_lookup, cb.qrzdb_lookup)


def main():
    parser = argparse.ArgumentParser(description="N1MM Logger+ VHF locator lookup")
    parser.add_argument("--port", type=int, default=cb.DEFAULT_PORT)
    parser.add_argument(
        "--config",
        default=os.path.join(cb.app_dir(), CONFIG_NAME),
        help="config file (same folder as the exe by default)",
    )
    args = parser.parse_args()

    settings = {}
    if os.path.exists(args.config):
        try:
            with open(args.config, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith(("#", "[")):
                        continue
                    if "=" not in line:
                        continue
                    key, _, val = [p.strip() for p in line.partition("=")]
                    settings[key.lower()] = val
        except OSError:
            pass

    port = args.port
    if "udp_port" in settings:
        try:
            port = int(settings["udp_port"])
        except ValueError:
            pass
    cache_days = cb.DEFAULT_CACHE_DAYS
    if "cache_days" in settings:
        try:
            cache_days = int(settings["cache_days"])
        except ValueError:
            pass
    cache_file = os.path.join(cb.app_dir(), CACHE_NAME)
    if "cache_file" in settings:
        cache_file = os.path.abspath(
            os.path.join(os.path.dirname(args.config), settings["cache_file"])
        )

    # Optional QRZ.com XML service (paid subscription). Empty credentials
    # keep QRZ out of the lookup chain.
    qrz_username = settings.get("qrz_username", "")
    qrz_password = settings.get("qrz_password", "")

    root = tk.Tk()
    VHFApp(root, cache_file, port, cache_days, qrz_username, qrz_password)
    root.mainloop()


if __name__ == "__main__":
    main()
