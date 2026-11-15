# SPDX-License-Identifier: Unlicense
"""Offline QRZ login/lookup regressions; no Tk or credentials required."""
import ast
from pathlib import Path
import re
import time
import unittest
import urllib.parse
import xml.etree.ElementTree as ET


class QRZTests(unittest.TestCase):
    def setUp(self):
        # Load the actual network functions without importing the Tk GUI.
        source = Path(__file__).resolve().parents[1] / 'n1mm_callbook.py'
        tree = ast.parse(source.read_text())
        names = {'_qrz_login', '_qrz_xml_lookup'}
        tree.body = [node for node in tree.body
                     if isinstance(node, ast.FunctionDef) and node.name in names]
        self.requests = []
        self.responses = []
        def get(url, headers, timeout):
            self.requests.append(url)
            return self.responses.pop(0)
        self.env = dict(re=re, time=time, urllib=urllib, ET=ET,
                        USER_AGENT='test', http_get=get, _QRZ_SESSION={},
                        _qrz_session_save=lambda: None, normalize_grid=lambda x: x)
        exec(compile(tree, str(source), 'exec'), self.env)

    def test_login_and_lookup_namespaces(self):
        for host in ('xml', 'xmldata'):
            with self.subTest(host=host):
                self.env['_QRZ_SESSION'].clear()
                self.responses = [
                    f'<QRZDatabase xmlns="http://{host}.qrz.com"><Session>'
                    '<Key>test-key</Key></Session></QRZDatabase>',
                    f'<QRZDatabase xmlns="http://{host}.qrz.com"><Session>'
                    '<SubExp>2027</SubExp></Session><Callsign><fname>Test</fname>'
                    '<grid>JN76AA</grid></Callsign></QRZDatabase>']
                result = self.env['_qrz_xml_lookup']('TEST', 'user', 'dummy')
                self.assertEqual(result['grid'], 'JN76AA')
                self.assertEqual(self.env['_QRZ_SUBEXP'], '2027')
                self.assertTrue(all(url.startswith('https://xmldata.qrz.com/')
                                    for url in self.requests))

    def test_login_session_error(self):
        self.responses = ['<QRZDatabase xmlns="http://xmldata.qrz.com">'
                          '<Session><Error>password incorrect</Error></Session>'
                          '</QRZDatabase>']
        self.assertEqual(self.env['_qrz_login']('user', 'dummy'),
                         (None, 'password incorrect'))

    def test_expired_session_is_discarded(self):
        self.env['_QRZ_SESSION']['user'] = {'key': 'expired', 'ts': time.time()}
        self.responses = ['<QRZDatabase xmlns="http://xmldata.qrz.com">'
                          '<Session><Error>session timeout</Error></Session>'
                          '</QRZDatabase>']
        self.assertIsNone(self.env['_qrz_xml_lookup']('TEST', 'user', 'dummy'))
        self.assertNotIn('user', self.env['_QRZ_SESSION'])


if __name__ == '__main__':
    unittest.main()
