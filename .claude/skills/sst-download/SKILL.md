---
name: sst-download
description: Batch-download SST data and PDF reports for a set of named coordinates, each with its own calendar days and years. Defaults to the MUR 1 km dataset with PDF generation on. Use when the user gives a list of coordinates/names plus dates or year ranges and asks to download the data or generate the reports, or invokes /sst-download.
---

# sst-download — named coordinates → CSV + one PDF per point

Runs through the **sst_viewer app's own batch endpoint**, so the fetch path,
the per-point series cache and `reports/template.qmd` are exactly the ones the
Data tab uses. Do not write a second fetch/render path.

(For the legacy RProject3 pipeline under `Manual\`, that is `sst-report`, a
different thing. Prefer this skill for anything the app's datasets cover.)

## Defaults

- dataset **`mur_okhotsk`** (GHRSST MUR 1 km)
- **PDF generation ON**
- series cache reused (set `"refresh": true` only when the user wants a
  re-download)

State the defaults you applied; only ask if the user's request contradicts
them or is genuinely ambiguous.

## 1. Turn what the user gave you into a spec

They typically give coordinates with names in one block and dates/years in
another. Pair them up yourself; do not make them restate it.

```json
{
  "points": [
    {"name": "Tikhoye 1.5 km", "lat": 48.74996558422831, "lon": 140.21045046833416,
     "md": ["06-05"], "years": [2023, 2026]}
  ]
}
```

- `md` — list of `"MM-DD"` calendar days for that point.
- `years` — `[from, to]` inclusive, or an explicit list (`[2019, 2023, 2025]`).
  A day that doesn't exist in a year (`02-29`) is skipped for that year.
- Optional top level: `"dataset"`, `"generate_pdf"`, `"refresh"`.

Every point needs a `name` — it becomes the PDF filename and the report title.

## 2. Make sure the app is running

`scripts\launch.ps1` (or the `launch-sst-viewer` skill). The helper fails with
a clear message if port 8000 is closed.

## 3. Dry-run, then run

```
conda run -n mfa_env python scripts\batch_download.py --dry-run -f spec.json
conda run -n mfa_env python scripts\batch_download.py -f spec.json
```

**Always dry-run first** and check the resolved dates against what the user
asked for — a real run costs roughly 15–20 s per point (fetch + Quarto), and a
wrong date list is only obvious afterwards.

The real run streams per-point progress and ends with the PDF/CSV paths.
Outputs land in `library\reports\` and
`library\downloads\`, and appear as download links in the Data tab.

## 4. Report back

Give the user the per-point values as a small table (point × year) plus the
file paths, and attach the files. Flag any value that breaks the pattern across
years or neighbouring points rather than passing it on silently.

## Gotchas

- **Do not drive the Data tab in the browser for this.** The UI calls
  `prompt()` for any unnamed point when PDFs are on and `alert()` on a bad date
  row; a browser dialog freezes the Chrome extension for the rest of the
  session. The API path has neither.
- Re-running the same point/dates is nearly free — the raw series is cached per
  coordinate under `library\series\`. Only the PDF re-renders.
- MUR is 1 km but the app snaps to the nearest ocean cell; a coordinate on land
  returns no data for that point rather than failing the whole job.
- 4 dates on one calendar day across 4 years is a thin series: the report
  template will correctly omit trend tests that need more years. That is the
  template working, not a bug.
