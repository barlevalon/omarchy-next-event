#!/usr/bin/python3 -S

import json
import os
import re
import sys
import tempfile
import urllib.request
from datetime import date, datetime, time, timedelta
from html import unescape
from pathlib import Path
from urllib.parse import urlsplit

# Always use the shipped calendar libraries, independent of site-packages.
sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))
sys.dont_write_bytecode = True

import recurring_ical_events
from icalendar import Calendar


CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "omarchy/calendar-feeds"
MAX_FEED_BYTES = 10 * 1024 * 1024
MAX_CONFIG_BYTES = 128 * 1024
MAX_FEEDS = 32
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def local_datetime(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.astimezone()
    return value.astimezone()


def meeting_url(component):
    fields = ("CONFERENCE", "X-GOOGLE-CONFERENCE", "URL", "LOCATION", "DESCRIPTION")
    for field in fields:
        for match in URL_PATTERN.findall(unescape(str(component.get(field, "")))):
            url = match.rstrip(".,;:!?)]}")
            parsed = urlsplit(url)
            host = (parsed.hostname or "").lower().rstrip(".")
            if parsed.scheme != "https" or parsed.username or parsed.password:
                continue
            if host == "meet.google.com" or host in {
                "teams.microsoft.com",
                "teams.live.com",
                "teams.cloud.microsoft",
            } or host == "zoom.us" or host.endswith(".zoom.us"):
                return url
    return ""


def events_in_feed(data, day_start, day_end):
    calendar = Calendar.from_ical(data)
    for component in recurring_ical_events.of(calendar).between(day_start, day_end):
        if str(component.get("STATUS", "")).upper() == "CANCELLED":
            continue
        start = local_datetime(component.decoded("DTSTART"))
        if start is None:  # All-day entries are not useful in a next-meeting label.
            continue
        raw_end = component.decoded("DTEND") if component.get("DTEND") else start
        end = local_datetime(raw_end) or start
        yield {
            "title": " ".join(str(component.get("SUMMARY", "Untitled")).split())[:120],
            "start": start,
            "end": max(start, end),
            "meeting_url": meeting_url(component),
        }


def upcoming_events(feeds, now):
    day_start = datetime.combine(now.date(), time.min, now.tzinfo)
    day_end = day_start + timedelta(days=1)
    events = []
    failures = 0

    for data in feeds:
        try:
            events.extend(events_in_feed(data, day_start, day_end))
        except Exception:
            failures += 1

    events = [event for event in events if event["start"] >= now or event["end"] > now]
    events.sort(key=lambda event: event["start"])
    return [{
        "title": event["title"],
        "start": event["start"].isoformat(),
        "end": event["end"].isoformat(),
        "ongoing": event["start"] <= now < event["end"],
        "meetingUrl": event["meeting_url"],
    } for event in events], failures


class ConfigError(Exception):
    """A configuration error safe to display without exposing feed secrets."""


def validate_url(value):
    if not isinstance(value, str):
        raise ConfigError("Enter an HTTPS calendar feed URL.")
    url = value.strip()
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname and parsed.port != 0
                 and not parsed.username and not parsed.password and not parsed.fragment
                 and not re.search(r"[\s\x00-\x1f\x7f]", url) and len(url) <= 8192)
    except ValueError:
        valid = False
    if not valid:
        raise ConfigError("Use a valid HTTPS feed URL without embedded credentials.")
    return url


def validate_urls(values):
    if not isinstance(values, list):
        raise ConfigError("Calendar feeds must be a list of HTTPS URLs.")
    if len(values) > MAX_FEEDS:
        raise ConfigError(f"Use at most {MAX_FEEDS} calendar feeds.")
    urls = []
    for index, value in enumerate(values):
        try:
            urls.append(validate_url(value))
        except ConfigError as error:
            raise ConfigError(f"Feed {index + 1}: {error}") from None
    if len(("\n".join(urls) + "\n").encode()) > MAX_CONFIG_BYTES:
        raise ConfigError("Calendar feed settings are too large.")
    return urls


def read_feed_urls():
    try:
        with CONFIG.open() as file:
            data = file.read(MAX_CONFIG_BYTES + 1)
    except FileNotFoundError:
        return []
    if len(data) > MAX_CONFIG_BYTES:
        raise ConfigError("Calendar feed settings are too large.")
    return [line.strip() for line in data.splitlines()
            if line.strip() and not line.strip().startswith("#")]


def feed_urls():
    return validate_urls(read_feed_urls())


def save_feed_urls(values):
    urls = validate_urls(values)
    CONFIG.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, filename = tempfile.mkstemp(prefix=".calendar-feeds-", dir=CONFIG.parent)
    try:
        with os.fdopen(descriptor, "w") as file:
            file.write("\n".join(urls) + ("\n" if urls else ""))
            file.flush()
            os.fsync(file.fileno())
        # mkstemp creates mode 0600; replacement is atomic and never follows a target symlink.
        os.replace(filename, CONFIG)
    finally:
        Path(filename).unlink(missing_ok=True)


class HTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        if urlsplit(new_url).scheme != "https":
            raise ValueError("Calendar redirects must use HTTPS")
        return super().redirect_request(request, response, code, message, headers, new_url)


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "omarchy-next-event/1.0"})
    opener = urllib.request.build_opener(HTTPSRedirectHandler())
    with opener.open(request, timeout=10) as response:
        data = response.read(MAX_FEED_BYTES + 1)
    if len(data) > MAX_FEED_BYTES:
        raise ValueError("Calendar feed is too large")
    return data


def test_feed_urls(values):
    if not isinstance(values, list):
        raise ConfigError("Calendar feeds must be a list of HTTPS URLs.")
    if len(values) > MAX_FEEDS:
        raise ConfigError(f"Use at most {MAX_FEEDS} calendar feeds.")
    results = []
    for value in values:
        try:
            url = validate_url(value)
        except ConfigError as error:
            results.append({"ok": False, "error": str(error)})
            continue
        try:
            calendar = Calendar.from_ical(fetch(url))
            if calendar.name != "VCALENDAR":
                raise ValueError("Not a calendar")
            results.append({"ok": True})
        except Exception:
            # HTTP/parse exceptions may contain bearer URLs or private calendar text.
            results.append({"ok": False, "error": "Could not read a calendar. Check its sharing link and connection."})
    return results


def configuration_main(action):
    try:
        if action == "read":
            result = {"status": "ok", "urls": read_feed_urls()}
        else:
            # Secrets travel over stdin, never process arguments or shell commands.
            payload = sys.stdin.readline(MAX_CONFIG_BYTES + 1)
            if len(payload) > MAX_CONFIG_BYTES:
                raise ConfigError("Calendar feed settings are too large.")
            try:
                values = json.loads(payload)["urls"]
            except (ValueError, KeyError, TypeError):
                raise ConfigError("Calendar settings request was invalid.") from None
            if action == "test":
                result = {"status": "ok", "results": test_feed_urls(values)}
            else:
                save_feed_urls(values)
                result = {"status": "ok"}
    except ConfigError as error:
        result = {"status": "error", "error": str(error)}
    except Exception:
        result = {"status": "error", "error": "Calendar settings could not be accessed or saved."}
    print(json.dumps(result))


def main():
    try:
        urls = feed_urls()
        if not urls:
            print(json.dumps({"status": "setup"}))
            return

        feeds = []
        failures = 0
        for url in urls:
            try:
                feeds.append(fetch(url))
            except Exception:
                failures += 1

        events, parse_failures = upcoming_events(feeds, datetime.now().astimezone())
        failures += parse_failures
        if not feeds:
            print(json.dumps({"status": "error", "error": "Calendar feeds unavailable"}))
        else:
            error = f"{failures} calendar feed failed" if failures else ""
            print(json.dumps({"status": "ok", "event": events[0] if events else None,
                              "events": events, "error": error}))
    except ConfigError as error:
        print(json.dumps({"status": "error", "error": str(error)}))
    except Exception:
        print(json.dumps({"status": "error", "error": "Calendar configuration unavailable"}))


def self_test():
    sample = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:recurring\r
DTSTART:20260829T150000Z\r
DTEND:20260829T153000Z\r
RRULE:FREQ=DAILY;COUNT=2\r
SUMMARY:Daily meeting\r
DESCRIPTION:Join https://meet.google.com/abc-defg-hij\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:overlapping\r
DTSTART:20260829T151000Z\r
DTEND:20260829T152000Z\r
SUMMARY:Overlapping meeting\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:all-day\r
DTSTART;VALUE=DATE:20260829\r
SUMMARY:Ignore me\r
END:VEVENT\r
END:VCALENDAR\r
"""
    now = datetime.fromisoformat("2026-08-29T14:00:00+00:00")
    events, failures = upcoming_events([sample], now)
    assert failures == 0
    assert len(events) == 2
    assert events[1]["title"] == "Overlapping meeting"
    event = events[0]
    assert event["title"] == "Daily meeting"
    assert datetime.fromisoformat(event["start"]).timestamp() == datetime.fromisoformat("2026-08-29T15:00:00+00:00").timestamp()
    assert event["meetingUrl"] == "https://meet.google.com/abc-defg-hij"

    malicious = Calendar.from_ical(b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:malicious\r
DTSTART:20260829T150000Z\r
DESCRIPTION:https://meet.google.com.evil.example/join\r
END:VEVENT\r
END:VCALENDAR\r
""").walk("VEVENT")[0]
    assert meeting_url(malicious) == ""
    print("ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    elif len(sys.argv) == 2 and sys.argv[1] in {"--feeds-read", "--feeds-test", "--feeds-save"}:
        configuration_main(sys.argv[1].removeprefix("--feeds-"))
    else:
        main()
