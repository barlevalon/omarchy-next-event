#!/usr/bin/python3
"""Run with /usr/bin/python3 test_feed_config.py; never touches real calendar settings."""

import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import next_event as backend


URL = "https://calendar.example/private/secret-token/basic.ics"
CALENDAR = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"


def response(action, values=None, raw=None):
    output = io.StringIO()
    payload = raw if raw is not None else json.dumps({"urls": values})
    with patch.object(sys, "stdin", io.StringIO(payload + "\n")), contextlib.redirect_stdout(output):
        backend.configuration_main(action)
    return json.loads(output.getvalue())


def main():
    with tempfile.TemporaryDirectory() as directory:
        config = Path(directory) / "omarchy/calendar-feeds"
        with patch.object(backend, "CONFIG", config):
            assert response("read") == {"status": "ok", "urls": []}
            assert response("save", [URL]) == {"status": "ok"}
            assert stat.S_IMODE(config.stat().st_mode) == 0o600
            assert config.read_text() == URL + "\n"
            assert response("read")["urls"] == [URL]

            config.write_text("# Existing format remains readable\n\n" + URL + "\n")
            assert backend.feed_urls() == [URL]
            config.chmod(0o644)
            backend.save_feed_urls([URL])
            assert stat.S_IMODE(config.stat().st_mode) == 0o600

            # Invalid edits never overwrite the existing file or echo the submitted secret.
            invalid = ["http://calendar.example/secret", "https://user:secret@calendar.example/", "file:///secret",
                       "https://", "https://calendar.example:99999/secret", "https://calendar.example/a\nsecret",
                       "https://calendar.example/a\x00secret", "https://calendar.example/#secret", "", None]
            for value in invalid:
                original = config.read_bytes()
                result = response("save", [value])
                assert result["status"] == "error"
                assert "secret" not in json.dumps(result)
                assert config.read_bytes() == original
            assert response("save", "not a list")["status"] == "error"
            assert response("save", [URL] * 33)["status"] == "error"
            assert response("test", [URL] * 33)["status"] == "error"
            assert response("save", raw="invalid JSON")["status"] == "error"
            assert response("save", raw="x" * (backend.MAX_CONFIG_BYTES + 1))["status"] == "error"

            original = config.read_bytes()
            for corrupt in [b"\xff", b"x" * (backend.MAX_CONFIG_BYTES + 1)]:
                config.write_bytes(corrupt)
                assert response("read")["status"] == "error"
                assert config.read_bytes() == corrupt, "Failed reads must preserve unknown existing settings"
            config.write_bytes(original)
            with patch.object(backend.os, "replace", side_effect=OSError(URL)):
                result = response("save", ["https://calendar.example/replacement"])
            assert result["status"] == "error" and URL not in json.dumps(result)
            assert config.read_bytes() == original
            assert not list(config.parent.glob(".calendar-feeds-*")), "Failed saves must remove temporary files"

            with patch.object(backend, "fetch", return_value=CALENDAR) as fetch:
                result = response("test", [URL])
                assert result == {"status": "ok", "results": [{"ok": True}]}
                fetch.assert_called_once_with(URL)
                assert config.read_bytes() == original, "Connection tests must never save"
            with patch.object(backend, "fetch", side_effect=RuntimeError(URL + " Private event title")):
                result = response("test", [URL])
                assert result["results"][0]["ok"] is False
                assert URL not in json.dumps(result) and "Private event title" not in json.dumps(result)
            with patch.object(backend, "fetch", return_value=b"<html>secret sign-in page</html>"):
                assert not response("test", [URL])["results"][0]["ok"]
            with patch.object(backend, "fetch", return_value=CALENDAR) as fetch:
                result = response("test", ["http://calendar.example/secret", URL])
                assert [item["ok"] for item in result["results"]] == [False, True]
                fetch.assert_called_once_with(URL)

            # A symlink target is not overwritten; the saved config becomes its own private file.
            target = Path(directory) / "unrelated"
            target.write_text("Keep this file")
            config.unlink()
            config.symlink_to(target)
            backend.save_feed_urls([URL])
            assert target.read_text() == "Keep this file"
            assert not config.is_symlink()
            assert stat.S_IMODE(config.stat().st_mode) == 0o600
            assert response("save", []) == {"status": "ok"}
            assert backend.feed_urls() == []
            assert response("read")["urls"] == []

        # Exercise the real stdin CLI, with an isolated config home and no network calls.
        home = Path(directory) / "cli"
        command = [sys.executable, str(Path(backend.__file__)), "--feeds-save"]
        saved = subprocess.run(command, input=json.dumps({"urls": [URL]}) + "\n", text=True,
                               capture_output=True, env={**os.environ, "XDG_CONFIG_HOME": str(home)}, check=True)
        assert json.loads(saved.stdout) == {"status": "ok"}
        assert URL not in saved.stdout + saved.stderr
        assert stat.S_IMODE((home / "omarchy/calendar-feeds").stat().st_mode) == 0o600
        read = subprocess.run(command[:-1] + ["--feeds-read"], text=True, capture_output=True,
                              env={**os.environ, "XDG_CONFIG_HOME": str(home)}, check=True)
        assert json.loads(read.stdout)["urls"] == [URL]

    request = backend.urllib.request.Request(URL)
    try:
        backend.HTTPSRedirectHandler().redirect_request(request, None, 302, "Redirect", {}, "http://calendar.example/secret")
    except ValueError as error:
        assert "secret" not in str(error)
    else:
        raise AssertionError("Reject HTTPS-to-HTTP redirects")
    print("ok: feed validation, connection tests, private atomic saves, stdin CLI, secret-safe errors")


if __name__ == "__main__":
    main()
