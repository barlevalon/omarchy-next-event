# Next event for Omarchy

A small, privacy-first meeting widget for the Omarchy bar. See the next timed
event today, notice overlaps, and choose which meeting to join without opening
a full calendar app.

- Read-only HTTPS iCalendar feeds, including recurring events.
- Titles hidden by default in the bar, tooltips, picker, and reminders.
- An overlap badge and explicit meeting picker, including identical schedules.
- Masked feed settings with connection testing and secure saves.
- Reminders 15 minutes before each event and at its start.

## Requirements

Omarchy Quattro with its built-in bar and `Ui.KeyboardPanel`. Tested on
**Omarchy 4.0.4**, with Python 3.14, `icalendar` 7.3.0, and
`recurring-ical-events` 3.8.2 and 3.9.0. This is not a standalone Waybar widget.

Install the Python dependencies from Arch's official repositories:

```sh
sudo pacman -S --needed python-icalendar python-recurring-ical-events
```

The helper uses `/usr/bin/python3`. Installing packages into a mise Python,
a virtual environment, or a user-managed Python does not install them for the
runtime helper. Node.js is needed only to run the development tests.

No installer script runs automatically. No sudo or pkexec is required by the
plugin at runtime.

## Install

After installing the dependencies:

```sh
omarchy plugin add https://github.com/barlevalon/omarchy-next-event.git --enable
```

Choose a bar section when prompted. The permanent plugin ID is
`alon.next-event`; the default placement is the center.

An existing plugin with that ID will not be overwritten. Back up local
modifications before replacing an earlier personal installation. Your feed
configuration is stored outside the plugin folder.

## Connect a calendar

1. Left-click **setup**, or middle-click the calendar widget.
2. Paste an **HTTPS ICS subscription URL** into the masked field.
3. Use **Add feed** for additional calendars.
4. Select **Test connection**. Each feed reports whether it is a valid calendar;
   testing does not save changes.
5. Select **Save & refresh**.

A calendar can connect successfully without having any timed events today.
**Cancel** discards unsaved edits. URLs are masked again whenever settings
reopens. Failed loads cannot overwrite unread settings; use **Retry load**.

### Find a subscription link

**Google Calendar, on the web:** Settings, choose a calendar under “Settings for
my calendars,” then Integrate calendar. Copy **Secret address in iCal format**.
See [Google's instructions](https://support.google.com/calendar/answer/37648).

**Outlook, on the web:** Settings, Calendar, Shared calendars, Publish a
calendar. Choose the calendar and permissions, then copy the **ICS** link,
not the HTML link. Publishing exposes the selected details to anyone with
that link. See [Microsoft's instructions](https://support.microsoft.com/en-us/outlook/share-your-calendar-in-outlook-com).

Workplace administrators may disable these options. Do not make a work
calendar public or bypass an organization's sharing policy to use this plugin.

## Controls

| Action | Result |
| --- | --- |
| Left-click a single event with a meeting link | Join the meeting |
| Left-click an overlapping event | Choose an event, then select Join meeting |
| Left-click setup, an error, or the empty calendar icon | Open feed settings |
| Middle-click | Open feed settings |
| Right-click | Toggle title privacy |
| Refresh calendar in settings | Refresh all widget instances |
| Escape or Cancel in a dialog | Close without joining or saving |

Join links are recognized for Google Meet, Microsoft Teams, and Zoom. Events
without a recognized link remain visible but cannot be joined from the picker.

Overlaps are direct intersections with the event shown in the bar.
Back-to-back and zero-duration events do not count. The bar keeps the
earliest-starting active or upcoming event as its primary entry.

## Privacy and storage

**Treat secret calendar URLs as passwords.** Anyone holding a bearer link may
be able to read the calendar. Do not include real links or private event data
in issues, screenshots, or Git repositories.

Feed settings are saved atomically to:

```text
${XDG_CONFIG_HOME:-~/.config}/omarchy/calendar-feeds
```

The saved file has owner-only permissions (`0600`). URLs travel to the helper
over stdin rather than command-line arguments. Connection errors do not expose
URLs or private calendar text. The file is plaintext, not encrypted.

Title privacy is a display setting, not access control. Feed requests still
download the calendar, and an explicit left-click can open a recognized meeting
link. Notifications contain no meeting action while privacy is on.

The plugin only reads feeds. It does not create, edit, or delete calendar events,
use OAuth, or send calendar data to an additional service. Plugins run
unsandboxed with the current user's privileges.

## Behavior and limitations

- Only active and upcoming timed events today are shown, in the system's local
  timezone. All-day and cancelled events are skipped.
- Feeds and the bar refresh every five minutes. Start/end display changes can
  therefore lag; reminders use a separate timer between refreshes.
- The helper accepts up to 32 HTTPS feeds, at most 10 MiB per response, with a
  ten-second network timeout per request. Connection tests run sequentially.
- Reminders are deduplicated within a widget instance, not persistently across
  shell restarts. Multiple monitors can currently produce duplicate reminders.
- Privacy hides titles but still shows times and the overlap count.

## Update or remove

Update:

```sh
omarchy plugin update alon.next-event
omarchy restart shell
```

Remove:

```sh
omarchy plugin remove alon.next-event
```

Removal asks for confirmation and removes the plugin, not your external feed
configuration. To clear stored URLs, remove every feed and save **before**
uninstalling. Revoking or resetting a provider's sharing link is a separate
action at the provider.

## Development checks

With the Python dependencies and Node.js installed:

```sh
/usr/bin/python3 next_event.py --self-test
/usr/bin/python3 test_feed_config.py
node privacy_test.cjs
node feed_settings_test.cjs
qmllint BarWidget.qml FeedSettings.qml
omarchy plugin validate .
```

Tests use synthetic data and temporary configurations, not real calendar feeds.
If using a virtual environment for development, keep it outside the plugin
checkout: Omarchy validation rejects symlinks inside plugin folders.
CI runs the Python and JavaScript checks in a fresh Arch Linux container.
Native dialog/focus behavior also needs a running Omarchy Wayland session.

## License

[MIT](LICENSE).
