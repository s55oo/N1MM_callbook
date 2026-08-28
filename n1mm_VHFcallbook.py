# SPDX-License-Identifier: Unlicense
"""N1MM Logger+ VHF Locator lookup.

A variant of the callbook app that shows the QRA/maidenhead locator
(e.g. JN76JG) of the worked station instead of the operator name. It
reuses the whole engine from ``n1mm_callbook`` - the same N1MM UDP
packets, the same QRZCQ.com / HamQTH.com / QRZ.com parsing, the same
parallel lookup and cache - and only overrides which field is shown.

The paid QRZ.com XML service is added as the first slot when credentials
are configured (set qrz_username/qrz_password in n1mm_VHFcallbook.cfg;
needs a QRZ XML subscription, https://www.qrz.com/page/xml_data.html).

Lookups are cached locally in n1mm_VHFcallbook_cache.json.

Made by S55OO with AI assistance.

Version: 1.14

Usage:
    python n1mm_VHFcallbook.py [--port 12060] [--config n1mm_VHFcallbook.cfg]
"""

__version__ = "1.14"

import n1mm_callbook as cb


class VHFApp(cb.CallbookApp):
    VERSION = __version__
    APP_TITLE = "N1MM VHF Callbook"
    # Locator only - no state / CQ zone / name. Each source's grid is
    # shown side by side (e.g. "JN76HD JN76HD JN76HD") so a wrong one
    # stands out.
    SLOT_FIELDS = ("grid",)
    SHOW_NAME = False
    # Slot order: QRZCQ, HamQTH's "Grid:" row, then the locator computed
    # from the coordinates on the public QRZ.com page. The paid QRZ XML
    # service is prepended automatically when credentials are configured.
    LOOKUP_CHAIN = (cb.qrzcq_lookup, cb.hamqth_lookup, cb.qrzdb_lookup)


def main():
    cb.run(
        VHFApp,
        "n1mm_VHFcallbook.cfg",
        "n1mm_VHFcallbook_cache.json",
        "N1MM Logger+ VHF locator lookup",
    )


if __name__ == "__main__":
    main()
