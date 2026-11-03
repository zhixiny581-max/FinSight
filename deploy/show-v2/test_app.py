import json
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import app


class AppTest(unittest.TestCase):
    def setUp(self):
        self.server = app.LimitedServer(("127.0.0.1", 0), app.Handler)
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.worker.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()

    def get(self, path):
        with urlopen(self.url + path, timeout=5) as resp:
            return json.load(resp)

    def test_ui_and_status(self):
        with urlopen(self.url + "/core", timeout=5) as resp:
            self.assertIn(b"/api/analyze", resp.read())
        self.assertEqual(self.get("/api/status")["source_commit"], "960b08e")

    def test_market_and_news_routing(self):
        with patch.object(app.MARKET, "market_kline", return_value=(200, {"ok": True, "item": {"bars": []}})) as fn:
            self.assertTrue(self.get("/api/market-kline?mode=latest")["ok"])
            fn.assert_called_once_with({"mode": ["latest"]})
        with patch.object(app.NEWS, "fetch_news", return_value={"ok": True, "mode": "cache", "items": []}):
            self.assertEqual(self.get("/api/news?include_imports=0")["mode"], "cache")

    def test_analysis_and_post_guard(self):
        with patch.object(app.base, "has_deepseek", return_value=True), \
                patch.object(app.MARKET, "market_context", return_value=None), \
                patch.object(app.MARKET, "attach_stocks", return_value=[]), \
                patch.object(app, "analyze", return_value={"verdict": {}}), \
                patch.object(app, "finalize_candidates"), patch.object(app.base, "mark_import_analyzed"):
            req = Request(self.url + "/api/analyze", data=b'{"news":{"title":"fixture"}}',
                          headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=5) as resp:
                self.assertTrue(json.load(resp)["ok"])
            req.add_header("Sec-Fetch-Site", "cross-site")
            with self.assertRaises(HTTPError) as failure:
                urlopen(req, timeout=5)
            self.assertEqual(failure.exception.code, 403)

    def test_web_fetch_rejects_private_addresses_and_ports(self):
        for url in ("http://127.0.0.1/", "http://169.254.169.254/", "https://example.org:8643/"):
            with self.subTest(url=url), self.assertRaises(app.base.ApiError):
                app.fetch_page(url, 1)
