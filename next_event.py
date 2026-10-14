#!/usr/bin/python3 -S

import contextlib
import fcntl
import hashlib
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

    for calendar_id, data in feeds:
        try:
            events.extend({**event, "calendarId": calendar_id}
                          for event in events_in_feed(data, day_start, day_end))
        except Exception:
            failures += 1

    events = [event for event in events if event["start"] >= now or event["end"] > now]
    events.sort(key=lambda event: event["start"])
    return [{
        "title": event["title"],
        "calendarId": event["calendarId"],
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


def validate_feeds(values):
    if not isinstance(values, list):
        raise ConfigError("Calendar feeds must be a list of named calendars.")
    if len(values) > MAX_FEEDS:
        raise ConfigError(f"Use at most {MAX_FEEDS} calendar feeds.")
    feeds = []
    ids = set()
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise ConfigError(f"Feed {index + 1}: Invalid calendar settings.")
        calendar_id = value.get("id")
        name = value.get("name")
        hidden = value.get("hideTitles")
        if (not isinstance(calendar_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", calendar_id)
                or calendar_id in ids):
            raise ConfigError(f"Feed {index + 1}: Calendar IDs must be unique.")
        if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 40
                or re.search(r"[\x00-\x1f\x7f]", name)):
            raise ConfigError(f"Feed {index + 1}: Enter a calendar name of 1–40 characters.")
        if not isinstance(hidden, bool):
            raise ConfigError(f"Feed {index + 1}: Choose whether to hide event titles.")
        try:
            url = validate_url(value.get("url"))
        except ConfigError as error:
            raise ConfigError(f"Feed {index + 1}: {error}") from None
        ids.add(calendar_id)
        feeds.append({"id": calendar_id, "name": name.strip(), "url": url, "hideTitles": hidden})
    if len((json.dumps(feeds, ensure_ascii=False) + "\n").encode()) > MAX_CONFIG_BYTES:
        raise ConfigError("Calendar feed settings are too large.")
    return feeds


def read_feeds():
    try:
        with CONFIG.open("rb") as file:
            data = file.read(MAX_CONFIG_BYTES + 1)
    except FileNotFoundError:
        return []
    if len(data) > MAX_CONFIG_BYTES:
        raise ConfigError("Calendar feed settings are too large.")
    data = data.decode("utf-8")
    if data.lstrip().startswith("["):
        try:
            return validate_feeds(json.loads(data))
        except ValueError:
            raise ConfigError("Calendar feed settings are invalid.") from None
    # Preserve existing URL-per-line subscriptions, assigning stable, secret-free IDs.
    urls = [line.strip() for line in data.splitlines()
            if line.strip() and not line.strip().startswith("#")]
    return validate_feeds([{
        "id": hashlib.sha256(f"{index}\n{url}".encode()).hexdigest()[:32],
        "name": f"Calendar {index + 1}", "url": url, "hideTitles": True,
    } for index, url in enumerate(urls)])


def calendar_settings(feeds):
    return [{key: feed[key] for key in ("id", "name", "hideTitles")} for feed in feeds]


@contextlib.contextmanager
def config_lock():
    """Serialize privacy read-modify-write with other configuration saves."""
    CONFIG.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(str(CONFIG) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def write_feeds(feeds):
    descriptor, filename = tempfile.mkstemp(prefix=".calendar-feeds-", dir=CONFIG.parent)
    try:
        with os.fdopen(descriptor, "w") as file:
            file.write(json.dumps(feeds, ensure_ascii=False) + "\n")
            file.flush()
            os.fsync(file.fileno())
        # mkstemp creates mode 0600; replacement is atomic and never follows a target symlink.
        os.replace(filename, CONFIG)
    finally:
        Path(filename).unlink(missing_ok=True)


def save_feeds(values):
    feeds = validate_feeds(values)
    with config_lock():
        write_feeds(feeds)
    return calendar_settings(feeds)


def set_calendar_privacy(calendar_id, hidden):
    if not isinstance(calendar_id, str) or not isinstance(hidden, bool):
        raise ConfigError("Calendar privacy request was invalid.")
    with config_lock():
        feeds = read_feeds()
        feed = next((feed for feed in feeds if feed["id"] == calendar_id), None)
        if feed is None:
            raise ConfigError("Calendar no longer exists. Refresh calendar settings.")
        feed["hideTitles"] = hidden
        write_feeds(feeds)
    return calendar_settings(feeds)


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
            result = {"status": "ok", "feeds": read_feeds()}
        else:
            # Secrets travel over stdin, never process arguments or shell commands.
            payload = sys.stdin.readline(MAX_CONFIG_BYTES + 1)
            if len(payload) > MAX_CONFIG_BYTES:
                raise ConfigError("Calendar feed settings are too large.")
            try:
                request = json.loads(payload)
                if not isinstance(request, dict):
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                raise ConfigError("Calendar settings request was invalid.") from None
            if action == "privacy":
                result = {"status": "ok", "calendars": set_calendar_privacy(
                    request.get("calendarId"), request.get("hideTitles"))}
            elif action == "test":
                result = {"status": "ok", "results": test_feed_urls(request.get("urls"))}
            else:
                result = {"status": "ok", "calendars": save_feeds(request.get("feeds"))}
    except ConfigError as error:
        result = {"status": "error", "error": str(error)}
    except Exception:
        result = {"status": "error", "error": "Calendar settings could not be accessed or saved."}
    print(json.dumps(result))


def main():
    try:
        configured = read_feeds()
        if not configured:
            print(json.dumps({"status": "setup"}))
            return

        feeds = []
        failures = 0
        for feed in configured:
            try:
                feeds.append((feed["id"], fetch(feed["url"])))
            except Exception:
                failures += 1

        events, parse_failures = upcoming_events(feeds, datetime.now().astimezone())
        failures += parse_failures
        if not feeds:
            print(json.dumps({"status": "error", "error": "Calendar feeds unavailable"}))
        else:
            error = f"{failures} calendar feed failed" if failures else ""
            print(json.dumps({"status": "ok", "event": events[0] if events else None,
                              "events": events, "calendars": calendar_settings(configured), "error": error}))
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
    events, failures = upcoming_events([("work", sample), ("personal", sample)], now)
    assert failures == 0
    assert len(events) == 4
    assert events[2]["title"] == "Overlapping meeting"
    assert [event["calendarId"] for event in events] == ["work", "personal", "work", "personal"]
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
    elif len(sys.argv) == 2 and sys.argv[1] in {"--feeds-read", "--feeds-test", "--feeds-save", "--feeds-privacy"}:
        configuration_main(sys.argv[1].removeprefix("--feeds-"))
    else:
        main()
