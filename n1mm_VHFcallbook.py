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

With ``vhfctest_share=yes`` in the .cfg the app also listens for
VHFCtest4WIN's multi-op sharing broadcasts (UDP port 6767): it picks the
callsign being typed straight out of them and runs the locator lookup
*before* the QSO is logged, so a wrong QRA locator can be caught while it
is still editable. See section 1 of the README.

Made by S55OO with AI assistance.

Version: 1.18

Usage:
    python n1mm_VHFcallbook.py [--port 12060] [--config n1mm_VHFcallbook.cfg]
"""

__version__ = "1.18"

import n1mm_callbook as cb


class VHFApp(cb.CallbookApp):
    VERSION = __version__
    APP_TITLE = "N1MM VHF Callbook"
    # The VHF variant can take VHFCtest4WIN's pre-log callsign feed
    # (enable it with vhfctest_share=yes in n1mm_VHFcallbook.cfg).
    VHFCTEST_CAPABLE = True
    # Locator only - no state / CQ zone / name. Each source's grid is
    # shown side by side, "JN76HD - JN76HD - JN76HD", so a wrong one
    # stands out; the text goes light green when all sources agree.
    SLOT_FIELDS = ("grid",)
    SLOT_SEP = " - "
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
