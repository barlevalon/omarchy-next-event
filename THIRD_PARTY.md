# Bundled Python components

Next Event includes the following pinned pure-Python components under
`vendor/`, including upstream tests, data, core metadata, and license notices.
Python source and license files remain unmodified.
It adds no package installation, build, or download step for users.

Original Next Event code is MIT-licensed. The components below are **not**
relicensed under MIT; their upstream licenses and copyright notices remain
with their source. `vendor-lock.json` records exact versions, official PyPI
wheel URLs, SHA-256 hashes, original wheel RECORD hashes, and bundled core
metadata hashes. Upstream long descriptions are omitted from every METADATA
file: their package-installation tutorials do not apply to a vendored plugin.
Core fields (versions, requirements, authors, license references) are retained.
Every other shipped file is verified against the original wheel RECORD.
No runtime installer or privilege mechanism is removed or hidden by this
metadata-only transformation.

| Component | Version | License notice |
| --- | --- | --- |
| icalendar | 7.3.0 | [BSD-2-Clause](vendor/icalendar-7.3.0.dist-info/licenses/LICENSE.rst) |
| recurring-ical-events | 3.8.2 | [LGPL-3.0-or-later](vendor/recurring_ical_events-3.8.2.dist-info/licenses/LICENSE) |
| python-dateutil | 2.9.0.post0 | [Apache-2.0 or BSD-3-Clause](vendor/python_dateutil-2.9.0.post0.dist-info/LICENSE) |
| six | 1.17.0 | [MIT](vendor/six-1.17.0.dist-info/LICENSE) |
| x-wr-timezone | 2.0.1 | [LGPL-3.0-or-later](vendor/x_wr_timezone-2.0.1.dist-info/LICENSE) |
| click | 8.5.0 | [BSD-3-Clause](vendor/click-8.5.0.dist-info/licenses/LICENSE.txt) |
| typing-extensions | 4.15.0 | [PSF-2.0](vendor/typing_extensions-4.15.0.dist-info/licenses/LICENSE) |

The LGPL libraries and their use are covered by the linked LGPL notices and
the accompanying [GNU GPL version 3](licenses/GPL-3.0.txt). All shipped library
source remains available and editable. The helper imports these files normally:
you may replace a library with an interface-compatible modified version.
No runtime hash enforcement, signing key, or rebuilding of Next Event is needed.
Bundle integrity checks are development checks, not execution restrictions.
After changing library files, restart the shell to ensure fresh helper imports.
Plugin updates may replace local edits; preserve your changes separately.

## Platform timezone database

Python’s standard `zoneinfo` uses Arch’s system `tzdata` database, already a
required dependency of `glibc` on Omarchy. The PyPI `tzdata` fallback wheel is
intentionally omitted: duplicating the operating system’s database adds no
runtime capability on this supported platform. The retained core metadata
still declares that cross-platform Python fallback.
This bundle is not intended for hosts without system IANA timezone data.
No timezone data is renamed, encoded, or unpacked at runtime.

## Restore the pinned bundle

This is a **maintainer-only** operation. The plugin never invokes this script.
It needs Python and network access to official PyPI wheel hosting, not pip.

1. From the repository root, move an existing `vendor/` directory aside.
2. Run `python3 tools/bundle_dependencies.py`.
3. Run `python3 -S test_bundle.py` and the other README development checks.
4. Review changes before publishing. The script refuses to overwrite an
   existing bundle and verifies each downloaded wheel against its pinned hash.

To update versions, select the intended upstream release and review its
dependency metadata, source, and licenses. Update the wheel URL/hash and RECORD
hash in `vendor-lock.json`, regenerate, update this notice, and run clean-Python
checks. Do not patch bundled files silently or add an automatic updater.
Omarchy reads the complete Git checkout; no runtime package manager is involved.
