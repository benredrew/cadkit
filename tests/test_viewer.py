"""Protocol-level tests for CadKit's viewer readiness boundary."""
from __future__ import annotations

import unittest
import os
import socket
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from cadkit import viewer


class _Socket:
    def __init__(self, data):
        self.data = data

    def receive(self):
        return self.data


class ViewerTests(unittest.TestCase):
    def test_browser_socket_recognises_only_browser_registration(self):
        client = viewer._BrowserSocket(_Socket("L:browser"))
        self.assertEqual(client.receive(), "L:browser")
        self.assertTrue(client.registered)

        python_client = viewer._BrowserSocket(_Socket("D:model"))
        self.assertEqual(python_client.receive(), "D:model")
        self.assertFalse(python_client.registered)

    @patch("cadkit.viewer.is_ready", return_value=False)
    @patch("cadkit.viewer.is_listening", return_value=True)
    def test_show_refuses_a_listener_without_a_browser(self, _listening, _ready):
        self.assertFalse(viewer.show(object(), port=3939, quiet=True))

    @patch("cadkit.viewer.wait_for_browser")
    @patch("cadkit.viewer.serve", return_value=(3939, "http://127.0.0.1:3939/"))
    def test_prepare_waits_after_opening_the_server(self, serve, wait):
        self.assertEqual(viewer.prepare(port=3939, name="test"), (3939, "http://127.0.0.1:3939/"))
        serve.assert_called_once_with(
            port=3939, name="test", open_window=True, wait=25.0, python=None
        )
        wait.assert_called_once_with(3939, wait=25.0)

    def test_model_is_sent_only_after_browser_registration(self):
        """The protocol sequence behind `toolbox preview` is race-free."""
        from websockets.sync.client import connect

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        with tempfile.TemporaryDirectory() as runtime, patch.dict(
            os.environ, {"XDG_RUNTIME_DIR": runtime}
        ):
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "cadkit.viewer",
                    "--server",
                    "--port",
                    str(port),
                    "--name",
                    "viewer-test",
                ],
                env=os.environ.copy(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                deadline = time.time() + 10
                while time.time() < deadline and not viewer.is_listening(port):
                    time.sleep(0.05)
                self.assertTrue(viewer.is_listening(port), "server did not start")
                self.assertFalse(viewer.show(object(), port=port, quiet=True))

                with connect(f"ws://127.0.0.1:{port}/", open_timeout=5) as browser:
                    browser.send("L:browser")
                    viewer.wait_for_browser(port, wait=5)

                    import cadquery as cq

                    self.assertTrue(viewer.show(cq.Workplane("XY").box(1, 1, 1), port=port, quiet=True))
                    payload = browser.recv(timeout=10)
                    self.assertTrue(payload, "registered browser received no model")
            finally:
                server.terminate()
                server.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
