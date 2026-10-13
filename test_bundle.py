#!/usr/bin/python3
"""Run with python3 -S test_bundle.py: no user or system site-packages."""

import base64
import csv
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import TZPATH, ZoneInfo

import next_event as backend
import typing_extensions


ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor"


def main():
    assert sys.flags.no_site, "Use python3 -S to exclude installed Python packages"
    # QML executes the helper directly: exercise its real shebang, not only -S tests.
    with tempfile.TemporaryDirectory() as directory:
        Path(directory, "sitecustomize.py").write_text("raise SystemExit(99)\n")
        result = subprocess.run([str(ROOT / "next_event.py"), "--self-test"],
                                env={**os.environ, "PYTHONPATH": directory},
                                text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
    lock = json.loads((ROOT / "vendor-lock.json").read_text())
    for package in lock["packages"]:
        distribution = importlib.metadata.distribution(package["name"])
        assert distribution.version == package["version"]
        assert Path(distribution.locate_file("")).resolve() == VENDOR
        record = VENDOR / package["record"]
        assert hashlib.sha256(record.read_bytes()).hexdigest() == package["record_sha256"]
        with record.open(newline="") as file:
            for name, digest, size in csv.reader(file):
                path = VENDOR / name
                assert path.resolve().is_relative_to(VENDOR) and not path.is_symlink()
                data = path.read_bytes()
                if Path(name).name == "METADATA" and Path(name).parent.name.endswith(".dist-info"):
                    assert data.partition(b"\n\n")[2] == b"", "Only core metadata is shipped"
                    assert len(data) == package["metadata_size"]
                    assert hashlib.sha256(data).hexdigest() == package["metadata_sha256"]
                    continue  # The upstream RECORD describes the original long description.
                if size:
                    assert len(data) == int(size), name
                if digest:
                    algorithm, expected = digest.split("=", 1)
                    actual = base64.urlsafe_b64encode(hashlib.new(algorithm, data).digest()).decode().rstrip("=")
                    assert actual == expected, name
    for name in ["icalendar", "recurring_ical_events", "dateutil", "six",
                 "x_wr_timezone", "click", "typing_extensions"]:
        module = sys.modules[name]
        assert Path(module.__file__).resolve().is_relative_to(VENDOR), name

    # Omarchy/Arch provides the database through glibc -> tzdata; no Python fallback.
    assert importlib.util.find_spec("tzdata") is None, "Do not ship a second timezone database"
    assert any((Path(path) / "America/New_York").is_file() for path in TZPATH)
    ZoneInfo.clear_cache()
    new_york = ZoneInfo("America/New_York")
    assert datetime(2026, 10, 25, 9, tzinfo=new_york).utcoffset().total_seconds() == -14400
    assert datetime(2026, 11, 1, 9, tzinfo=new_york).utcoffset().total_seconds() == -18000

    calendar = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:bundled-demo\r
DTSTART;TZID=America/New_York:20261025T090000\r
DTEND;TZID=America/New_York:20261025T100000\r
RRULE:FREQ=WEEKLY;COUNT=3\r
EXDATE;TZID=America/New_York:20261108T090000\r
SUMMARY:Demo weekly meeting\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:bundled-demo\r
RECURRENCE-ID;TZID=America/New_York:20261101T090000\r
DTSTART;TZID=America/New_York:20261101T110000\r
DTEND;TZID=America/New_York:20261101T120000\r
SUMMARY:Demo rescheduled meeting\r
END:VEVENT\r
END:VCALENDAR\r
"""
    for day, expected_hour, expected_title in [
        (25, 13, "Demo weekly meeting"),
        (1, 16, "Demo rescheduled meeting"),
        (8, None, None),
    ]:
        month = 10 if day == 25 else 11
        now = datetime(2026, month, day, tzinfo=timezone.utc)
        events, failures = backend.upcoming_events([calendar], now)
        assert failures == 0
        if expected_hour is None:
            assert events == [], "EXDATE must exclude the occurrence"
        else:
            assert len(events) == 1
            assert events[0]["title"] == expected_title
            assert datetime.fromisoformat(events[0]["start"]).timestamp() == now.replace(hour=expected_hour).timestamp()
    # Provider-defined VTIMEZONEs still work when the TZID is not in the OS database.
    custom_calendar = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VTIMEZONE\r
TZID:Demo/Custom\r
BEGIN:STANDARD\r
DTSTART:19700101T000000\r
TZOFFSETFROM:+0230\r
TZOFFSETTO:+0230\r
TZNAME:Demo\r
END:STANDARD\r
END:VTIMEZONE\r
BEGIN:VEVENT\r
UID:custom-timezone-demo\r
DTSTART;TZID=Demo/Custom:20261025T090000\r
DTEND;TZID=Demo/Custom:20261025T100000\r
SUMMARY:Demo custom timezone\r
END:VEVENT\r
END:VCALENDAR\r
"""
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    events, failures = backend.upcoming_events([custom_calendar], now)
    assert failures == 0 and len(events) == 1
    assert datetime.fromisoformat(events[0]["start"]).timestamp() == now.replace(hour=6, minute=30).timestamp()
    print("ok: pinned bundle integrity, local imports without site-packages, system timezone data, DST, recurrence exceptions, custom VTIMEZONE")


if __name__ == "__main__":
    main()
