# SPDX-License-Identifier: Unlicense
"""Offline HamQTH XML API tests (canned replies; no Tk, no network).

The XML format follows https://www.hamqth.com/developers.php - the same
login/session/search flow as github.com/kevinhooke/HamQTHClient.
"""
import ast
from pathlib import Path
import re
import threading
import time
import unittest
import urllib.parse
import xml.etree.ElementTree as ET

LOGIN_OK = ('<?xml version="1.0"?><HamQTH version="2.0" xmlns="https://www.hamqth.com">'
            '<session><session_id>09b0ae90050be03c452ad235a1f2915ad684393c</session_id>'
            '</session></HamQTH>')
LOGIN_BAD = ('<?xml version="1.0"?><HamQTH version="2.0" xmlns="https://www.hamqth.com">'
             '<session><error>Wrong user name or password</error></session></HamQTH>')
SEARCH = ('<?xml version="1.0"?><HamQTH version="2.0" xmlns="http://www.hamqth.com"><search>'
          '<callsign>kk6dct</callsign><nick>Kevin</nick><qth>Davis</qth>'
          '<country>United States</country><itu>6</itu><cq>3</cq><grid>cm98dn</grid>'
          '<adr_name>Kevin J Hooke</adr_name><us_state>CA</us_state></search></HamQTH>')
NOT_FOUND = ('<?xml version="1.0"?><HamQTH version="2.0" xmlns="https://www.hamqth.com">'
             '<session><error>Callsign not found</error></session></HamQTH>')
EXPIRED = ('<?xml version="1.0"?><HamQTH version="2.0" xmlns="https://www.hamqth.com">'
           '<session><error>Session does not exist or expired</error></session></HamQTH>')
NAMES = {"_hamqth_xml", "_hamqth_login", "_hamqth_xml_lookup", "hamqth_lookup",
         "set_hamqth_login"}
CONSTS = {"HAMQTH_XML", "HAMQTH_PRG", "HAMQTH_SESSION_TTL", "_HAMQTH_LOGIN",
          "_HAMQTH_SESSION", "_HAMQTH_SESSION_LOCK", "_HAMQTH_TIER"}


class HamQTHTests(unittest.TestCase):
    def setUp(self):
        src = Path(__file__).resolve().parents[1] / "n1mm_callbook.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        keep = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in NAMES:
                keep.append(node)
            elif isinstance(node, ast.Assign) and any(
                    getattr(t, "id", "") in CONSTS for t in node.targets):
                keep.append(node)
        tree.body = keep
        self.requests, self.responses, self.web_calls = [], [], []

        def get(url, headers, timeout):
            self.requests.append(url)
            return self.responses.pop(0)

        def web(call, timeout=15):
            self.web_calls.append(call)
            return {"name": "", "qth": "", "grid": "", "class": "", "state": "",
                    "cqzone": "", "country": ""}

        self.env = dict(re=re, time=time, urllib=urllib, ET=ET, threading=threading,
                        USER_AGENT="test", http_get=get, normalize_grid=str.upper,
                        _hamqth_web_lookup=web)
        exec(compile(tree, str(src), "exec"), self.env)
        self.env["set_hamqth_login"]("S55OO", "secret")

    def lookup(self, call="KK6DCT"):
        return self.env["hamqth_lookup"](call)

    def test_login_then_search(self):
        self.responses = [LOGIN_OK, SEARCH]
        r = self.lookup()
        self.assertEqual(r["name"], "Kevin")
        self.assertEqual(r["grid"], "CM98DN")
        self.assertEqual(r["cqzone"], "3")
        self.assertEqual(r["state"], "CA")
        self.assertEqual(r["country"], "United States")
        self.assertEqual(self.env["_HAMQTH_TIER"], "xml")
        self.assertIn("u=S55OO", self.requests[0])
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.requests[1]).query)
        self.assertEqual(q["callsign"], ["KK6DCT"])
        self.assertEqual(q["id"], ["09b0ae90050be03c452ad235a1f2915ad684393c"])
        self.assertIn("prg", q)

    def test_session_reused(self):
        self.responses = [LOGIN_OK, SEARCH, SEARCH]
        self.lookup()
        self.lookup()
        self.assertEqual(sum("u=S55OO" in u for u in self.requests), 1)

    def test_not_found_is_no_data_not_failure(self):
        self.responses = [LOGIN_OK, NOT_FOUND]
        self.assertEqual(self.lookup("XX9XX"), {})
        self.assertEqual(self.web_calls, [])

    def test_bad_login_falls_back_to_web(self):
        self.responses = [LOGIN_BAD]
        r = self.lookup()
        self.assertEqual(self.web_calls, ["KK6DCT"])
        self.assertEqual(self.env["_HAMQTH_TIER"], "web")
        self.assertIsNotNone(r)

    def test_expired_session_relogs_next_time(self):
        self.responses = [LOGIN_OK, EXPIRED]
        self.lookup()                       # expired -> web fallback this time
        self.assertEqual(self.env["_HAMQTH_SESSION"], {})
        self.responses = [LOGIN_OK, SEARCH]
        self.assertEqual(self.lookup()["name"], "Kevin")

    def test_no_login_uses_web_only(self):
        self.env["set_hamqth_login"]("", "")
        self.lookup()
        self.assertEqual(self.requests, [])
        self.assertEqual(self.web_calls, ["KK6DCT"])


if __name__ == "__main__":
    unittest.main()
