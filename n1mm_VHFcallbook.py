# SPDX-License-Identifier: Unlicense
"""N1MM Logger+ VHF Locator lookup.

A variant of the callbook app that shows the QRA/maidenhead locator
(e.g. JN76JG) of the worked station, with the operator name in front of
it, instead of the HF state/CQ-zone view. It reuses the whole engine from
``n1mm_callbook`` - the same N1MM UDP packets, the same QRZCQ.com /
HamQTH.com / QRZ.com parsing, the same parallel lookup and cache - and
only overrides which field is shown. Each source's locator is listed side
by side; when they all agree the row collapses to a single locator in a
larger green font ("Hans - JN76HD").

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

Version: 1.20

Usage:
    python n1mm_VHFcallbook.py [--port 12060] [--config n1mm_VHFcallbook.cfg]
"""

__version__ = "1.20"

import n1mm_callbook as cb


class VHFApp(cb.CallbookApp):
    VERSION = __version__
    APP_TITLE = "N1MM VHF Callbook"
    # The VHF variant can take VHFCtest4WIN's pre-log callsign feed
    # (enable it with vhfctest_share=yes in n1mm_VHFcallbook.cfg).
    VHFCTEST_CAPABLE = True
    # Locator per source, shown side by side ("JN76GB - JN76HD - JN76HD")
    # so a wrong one stands out, with the operator name (from the callbook)
    # in front of it. When every source that answered agrees, the row
    # collapses to one locator in a larger font and turns light green -
    # "Hans - JN76HD" - a quick "grid confirmed" signal.
    SLOT_FIELDS = ("grid",)
    SLOT_SEP = " - "
    SHOW_NAME = True
    DX_COUNTRY = False        # locator-focused: no " (Country)" after the name
    COLLAPSE_ON_AGREE = True
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
