---
name: launch-sst-viewer
description: Restart the sst_viewer web app (always a fresh server) and open it in the browser. Use when the user asks to launch/open/start/restart sst_viewer, run the SST map app, or invokes /launch-sst-viewer — and whenever /run needs this app running.
---

# launch-sst-viewer — kill the old server, start a fresh one

Everything is in `scripts\launch.ps1`. Just run it:

```
powershell -File "scripts\launch.ps1"
```

**Every launch replaces the running instance.** The script kills whatever is
listening on port 8000 first, then starts `uvicorn app:app --port 8000` in the
background (via the `mfa_env` python directly, no console window), polls until
it responds (up to 30 s), and opens `http://localhost:8000` in the default
browser. This is deliberate: uvicorn runs without `--reload`, so reusing an
already-running server silently serves the pre-edit `app.py` / `datasets.py` /
`reports.py`. stdout/stderr go to `cache\uvicorn.log` / `uvicorn.err.log` —
check those if it fails to come up.

The same applies to `/run`: restart through this script, never smoke-test
against a server that happens to still be up.

No interview needed — there's nothing to configure, just run it and report
the URL.

## Don't pile up browser tabs

If the app is already open in a tab, start the server with `-NoBrowser` and
reload that tab instead of opening another:

```
powershell -File "scripts\launch.ps1" -NoBrowser
```

A tab Claude opens to drive the app is Claude's to close again when done.

## Stopping it by hand

Closing the browser does NOT stop the server. To stop it without relaunching:

```
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'uvicorn|app:app' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

(`pkill -f` from Git Bash does NOT match native Windows command lines and
will silently do nothing.)

## Careful: the browser caches the frontend

`reports\template.qmd` and the `static\` files are read fresh per request, but
the browser caches `index.html` and `app.js` — bump the `app.js?v=N` query in
`static\index.html` after editing them, or the page keeps running the old copy.
(The server side no longer needs a manual restart: launching does it.)
