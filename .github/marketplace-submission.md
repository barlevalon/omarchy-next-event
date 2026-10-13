### Repository URL

https://github.com/barlevalon/omarchy-next-event

### Category

Productivity

### Tags

Bar, Quickshell

### Suggest a missing tag

_No response_

### Maintainer notes

I built Next Event as a lightweight meeting companion for the Omarchy bar,
not another full calendar. It brings upcoming meetings from multiple calendars
within reach, gives timely reminders, and opens Google Meet, Teams, or Zoom
without hunting through tabs. Privacy is an easily toggled mode: right-click
to hide event titles. An explicit picker keeps overlapping meetings accessible.

The permanent ID is `io.github.barlevalon.next-event`, renamed from the early
`alon.next-event` ID before marketplace listing. Please review the identifier
change on this existing submission rather than creating a second listing.
The preview is composed from native captures with fictional meetings and feeds;
no private calendar data is included.

System Python 3.10+ is required; calendar libraries are bundled as pinned,
unmodified source with upstream licenses and hashes. Timezones come from Arch’s
existing `tzdata` database, already required by `glibc`; there is no duplicate
Python timezone database. There are no additional Python package installation
steps, runtime downloads, or elevated privileges. THIRD_PARTY.md documents every bundled component,
including LGPL-licensed libraries, and how to replace or rebuild the bundle.
The README documents installation, removal, provider setup, and limitations.
Feed configuration is outside the repository and saved with owner-only
permissions.

### Submission checklist

- [ ] The repository is public and contains installation and removal instructions.
- [ ] I have documented the plugin license and any external dependencies.
- [ ] I confirm that I own or have permission to submit this plugin and its preview assets.
- [ ] The plugin does not overwrite user configuration without explicit consent.
- [ ] I understand that approval is for listing and is not a security review.
