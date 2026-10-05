import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from app.server import Handler


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def request(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        return json.load(urllib.request.urlopen(request, timeout=5))

    def test_health_sample_and_invalid_topology_http(self):
        self.assertEqual(self.request("/api/health")["status"], "ok")
        mesh = self.request("/api/samples/closed_tetra")
        prep = self.request("/api/prepare", mesh)
        self.assertFalse(prep["valid_for_solve"])
        self.assertEqual(prep["witness"]["kind"], "closed_surface")

    def test_http_validation_error_has_400(self):
        payload = {"positions": [[0, 0, 0], [1, 0, 0]], "faces": [[0, 0, 1]]}
        request = urllib.request.Request(
            f"{self.base}/api/prepare",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(request)
        self.assertEqual(context.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
