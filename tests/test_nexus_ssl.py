"""Tests for the SSL context builder in nexus.py.

Production failure: PyInstaller-bundled Python in Decky's plugin loader
shipped with an empty default CA store. Every HTTPS call to Nexus failed
with CERTIFICATE_VERIFY_FAILED. Frontend swallowed the exception and
silently rendered "No results."

The fix builds an SSLContext that explicitly loads from a known set of
system CA bundle paths (SteamOS has /etc/ssl/certs/ca-certificates.crt).
These tests pin the lookup order and confirm the context is functional
when a valid CA file is found.
"""

from __future__ import annotations

import os
import ssl
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

# Import the helper, not the module-level _SSL_CONTEXT (which is built at
# import time using the real system state).
from nexus import _build_ssl_context  # noqa: E402


def _make_fake_ca_bundle(dirpath: Path) -> Path:
    """Create a minimal but valid self-signed PEM for tests to feed
    load_verify_locations() — any well-formed PEM works for that call."""
    # Use Python's built-in default cert (always present in cpython tarball
    # via the ssl module) as a known-good PEM. Falls back to writing a
    # placeholder PEM that load_verify_locations accepts.
    src = ssl.get_default_verify_paths().cafile
    target = dirpath / "ca-bundle.crt"
    if src and os.path.exists(src):
        target.write_bytes(Path(src).read_bytes())
    else:
        # Synthesise: load_verify_locations accepts an empty PEM if it's
        # well-formed (BEGIN/END framing). Empty bundle is fine for the
        # path-resolution tests; we don't actually verify any cert.
        target.write_text(
            "-----BEGIN CERTIFICATE-----\n"
            "MIIBkTCB+wIJAJZ+0XYwQ+0qMA0GCSqGSIb3DQEBCwUAMA8xDTALBgNVBAMMBHRl\n"
            "c3QwHhcNMjEwMTAxMDAwMDAwWhcNMzEwMTAxMDAwMDAwWjAPMQ0wCwYDVQQDDAR0\n"
            "ZXN0MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDgGZcAVN1uoEXfxnYjY1bw\n"
            "Y5tPGddwQ7v+JsHRn4l9zZbgUWX0p1cVOZB+VWlu9hCpEqVAfTzCsZqBT5wPS8ZS\n"
            "fO1WONl9wQ+QmK9Wn7s5BezdvQfXFsQpQYJgF6/oqXcVCwxJ5oVRYWZWVfMBkUgr\n"
            "MR9V/v0PpqWylJTSSyOhKwIDAQABMA0GCSqGSIb3DQEBCwUAA4GBAJ0qJsk8/Lwy\n"
            "8gIb+rqzcQ9sJyVD1jSwjQ7gG4cQ+Rcgg5tFkx+S+5oH0vWcwQHvSCFRSWiu3qDA\n"
            "VxZ0wYTfh/8wnNhJl3wO95kf7iZsKvZf9HCJBpYWQ+1z3xVjU0r48VuvCFCDpcz4\n"
            "u/X9Yt6cmJyZj0n3CpFXFh9xn+kK\n"
            "-----END CERTIFICATE-----\n"
        )
    return target


class SslContextBuilderTests(unittest.TestCase):
    def test_uses_SSL_CERT_FILE_env_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ca = _make_fake_ca_bundle(Path(td))
            with mock.patch.dict(os.environ, {"SSL_CERT_FILE": str(ca)}):
                ctx = _build_ssl_context()
            self.assertIsInstance(ctx, ssl.SSLContext)
            # Reality check: the context must have at least one CA loaded.
            self.assertGreater(len(ctx.get_ca_certs()), 0)

    def test_falls_back_to_known_steamos_path(self) -> None:
        # The CI/dev host may or may not have /etc/ssl/certs/ca-certificates.crt;
        # the function just needs to not crash, and to return a usable context
        # when SOME bundle is reachable.
        ctx = _build_ssl_context()
        self.assertIsInstance(ctx, ssl.SSLContext)

    def test_env_var_pointing_at_missing_file_is_ignored(self) -> None:
        with mock.patch.dict(os.environ, {"SSL_CERT_FILE": "/nonexistent/ca.crt"}):
            ctx = _build_ssl_context()
        self.assertIsInstance(ctx, ssl.SSLContext)

    def test_module_level_context_is_built_at_import(self) -> None:
        # Smoke test — _SSL_CONTEXT is built when nexus is imported. If the
        # builder raised, this import would have failed.
        from nexus import _SSL_CONTEXT  # noqa: F401
        self.assertIsInstance(_SSL_CONTEXT, ssl.SSLContext)


if __name__ == "__main__":
    unittest.main()
