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
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import next_event as backend


URL = "https://calendar.example/private/secret-token/basic.ics"
CALENDAR = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
FEED = {"id": "work", "name": "Work", "url": URL, "hideTitles": True}


def response(action, values=None, raw=None):
    output = io.StringIO()
    payload = raw if raw is not None else json.dumps({"urls" if action == "test" else "feeds": values})
    with patch.object(sys, "stdin", io.StringIO(payload + "\n")), contextlib.redirect_stdout(output):
        backend.configuration_main(action)
    return json.loads(output.getvalue())


def main():
    with tempfile.TemporaryDirectory() as directory:
        config = Path(directory) / "omarchy/calendar-feeds"
        with patch.object(backend, "CONFIG", config):
            assert response("read") == {"status": "ok", "feeds": []}
            assert response("save", [FEED]) == {"status": "ok", "calendars": backend.calendar_settings([FEED])}
            assert stat.S_IMODE(config.stat().st_mode) == 0o600
            assert json.loads(config.read_text()) == [FEED]
            assert response("read")["feeds"] == [FEED]

            config.write_text("# Existing format remains readable\n\n" + URL + "\n")
            legacy = backend.read_feeds()
            assert legacy[0]["url"] == URL and legacy[0]["hideTitles"] is True
            assert legacy[0]["name"] == "Calendar 1"
            assert backend.read_feeds() == legacy, "Legacy IDs must be stable before saving"
            config.chmod(0o644)
            backend.save_feeds(legacy)
            assert backend.read_feeds() == legacy
            assert stat.S_IMODE(config.stat().st_mode) == 0o600
            backend.set_calendar_privacy(legacy[0]["id"], False)
            assert backend.read_feeds() == [{**legacy[0], "hideTitles": False}], "First right-click migrates existing subscriptions"

            # Invalid edits never overwrite the existing file or echo the submitted secret.
            invalid = ["http://calendar.example/secret", "https://user:secret@calendar.example/", "file:///secret",
                       "https://", "https://calendar.example:99999/secret", "https://calendar.example/a\nsecret",
                       "https://calendar.example/a\x00secret", "https://calendar.example/#secret", "", None]
            for value in invalid:
                original = config.read_bytes()
                result = response("save", [{**FEED, "url": value}])
                assert result["status"] == "error"
                assert "secret" not in json.dumps(result)
                assert config.read_bytes() == original
            assert response("save", "not a list")["status"] == "error"
            assert response("save", [FEED] * 33)["status"] == "error"
            assert response("test", [URL] * 33)["status"] == "error"
            assert response("save", raw="invalid JSON")["status"] == "error"
            assert response("save", raw="x" * (backend.MAX_CONFIG_BYTES + 1))["status"] == "error"

            for invalid_feed in [None, {}, {**FEED, "id": ""}, {**FEED, "name": ""},
                                 {**FEED, "name": "x" * 41}, {**FEED, "name": "secret\nname"},
                                 {**FEED, "hideTitles": "false"}, {**FEED, "hideTitles": 0}]:
                original = config.read_bytes()
                assert response("save", [invalid_feed])["status"] == "error"
                assert config.read_bytes() == original
            assert response("save", [FEED, FEED])["status"] == "error"

            original = config.read_bytes()
            for corrupt in [b"\xff", b"x" * (backend.MAX_CONFIG_BYTES + 1), b"[invalid JSON",
                            json.dumps([{**FEED, "hideTitles": "false"}]).encode()]:
                config.write_bytes(corrupt)
                assert response("read")["status"] == "error"
                assert config.read_bytes() == corrupt, "Failed reads must preserve unknown existing settings"
            config.write_bytes(original)
            with patch.object(backend.os, "replace", side_effect=OSError(URL)):
                result = response("save", [{**FEED, "url": "https://calendar.example/replacement"}])
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

            # Right-click updates only the requested calendar and returns no subscription secrets.
            personal = {**FEED, "id": "personal", "name": "Personal", "hideTitles": False}
            assert response("save", [FEED, personal])["status"] == "ok"
            result = response("privacy", raw=json.dumps({"calendarId": "work", "hideTitles": False}))
            assert result == {"status": "ok", "calendars": [
                {"id": "work", "name": "Work", "hideTitles": False},
                {"id": "personal", "name": "Personal", "hideTitles": False}]}
            assert URL not in json.dumps(result)
            assert backend.read_feeds() == [{**FEED, "hideTitles": False}, personal]
            original = config.read_bytes()
            for payload in [{"calendarId": "missing", "hideTitles": True},
                            {"calendarId": "work", "hideTitles": "false"}, {}]:
                assert response("privacy", raw=json.dumps(payload))["status"] == "error"
                assert config.read_bytes() == original
            with patch.object(backend.os, "replace", side_effect=OSError(URL)):
                assert response("privacy", raw=json.dumps({"calendarId": "work", "hideTitles": True}))["status"] == "error"
            assert config.read_bytes() == original

            # Fetch failures must not shift calendar identity or leak feed URLs in event output.
            now = datetime.now().astimezone()
            start = now.replace(hour=0, minute=0, second=0).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            end = (now + timedelta(hours=1)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            event_calendar = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:demo\r\n"
                              f"DTSTART:{start}\r\nDTEND:{end}\r\nSUMMARY:Demo meeting\r\n"
                              "END:VEVENT\r\nEND:VCALENDAR\r\n").encode()
            with (patch.object(backend, "fetch", side_effect=[RuntimeError(URL), event_calendar]),
                  contextlib.redirect_stdout(io.StringIO()) as output):
                backend.main()
            result = json.loads(output.getvalue())
            assert result["status"] == "ok" and len(result["calendars"]) == 2
            assert result["events"][0]["calendarId"] == "personal"
            assert URL not in json.dumps(result)

            # Renaming/reordering calendars preserves identity and their saved privacy.
            renamed = {**personal, "name": "Home"}
            backend.save_feeds([renamed, {**FEED, "hideTitles": False}])
            backend.set_calendar_privacy("work", True)
            assert backend.read_feeds() == [renamed, FEED]

            # A symlink target is not overwritten; the saved config becomes its own private file.
            target = Path(directory) / "unrelated"
            target.write_text("Keep this file")
            config.unlink()
            config.symlink_to(target)
            backend.save_feeds([FEED])
            assert target.read_text() == "Keep this file"
            assert not config.is_symlink()
            assert stat.S_IMODE(config.stat().st_mode) == 0o600
            assert response("save", []) == {"status": "ok", "calendars": []}
            assert backend.read_feeds() == []
            assert response("read")["feeds"] == []

        # Exercise the real stdin CLI, with an isolated config home and no network calls.
        home = Path(directory) / "cli"
        command = [sys.executable, "-S", str(Path(backend.__file__)), "--feeds-save"]
        saved = subprocess.run(command, input=json.dumps({"feeds": [FEED]}) + "\n", text=True,
                               capture_output=True, env={**os.environ, "XDG_CONFIG_HOME": str(home)}, check=True)
        assert json.loads(saved.stdout) == {"status": "ok", "calendars": backend.calendar_settings([FEED])}
        assert URL not in saved.stdout + saved.stderr
        assert stat.S_IMODE((home / "omarchy/calendar-feeds").stat().st_mode) == 0o600
        read = subprocess.run(command[:-1] + ["--feeds-read"], text=True, capture_output=True,
                              env={**os.environ, "XDG_CONFIG_HOME": str(home)}, check=True)
        assert json.loads(read.stdout)["feeds"] == [FEED]

        # Concurrent per-calendar updates must not overwrite each other.
        subprocess.run(command, input=json.dumps({"feeds": [FEED, personal]}) + "\n", text=True,
                       capture_output=True, env={**os.environ, "XDG_CONFIG_HOME": str(home)}, check=True)
        def privacy_request(calendar_id, hidden):
            result = subprocess.run(command[:-1] + ["--feeds-privacy"],
                                    input=json.dumps({"calendarId": calendar_id, "hideTitles": hidden}) + "\n",
                                    text=True, capture_output=True,
                                    env={**os.environ, "XDG_CONFIG_HOME": str(home)}, check=True)
            assert json.loads(result.stdout)["status"] == "ok"
        with ThreadPoolExecutor(max_workers=2) as pool:
            work = pool.submit(privacy_request, "work", False)
            home_calendar = pool.submit(privacy_request, "personal", True)
            work.result()
            home_calendar.result()
        stored = json.loads((home / "omarchy/calendar-feeds").read_text())
        assert stored == [{**FEED, "hideTitles": False}, {**personal, "hideTitles": True}]

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
