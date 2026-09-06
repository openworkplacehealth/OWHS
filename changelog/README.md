# Changelog entries

One JSON file per change, rendered into `site/changelog.html` by `tools/build_changelog.py`. Fields: `tab` (registry, specification or site), `date` (YYYY-MM-DD, or YYYY-MM when only the month is known), `shown` (the date as printed), `html` (one line of row text; links allowed; no table markup), `version` (registry and specification entries only) and an optional `order` to place entries that share a date, higher first. Name the file `<date>-<tab>-<a few words>.json`. Run the build after adding a file; the check in CI refuses a page that is not a fresh render.
