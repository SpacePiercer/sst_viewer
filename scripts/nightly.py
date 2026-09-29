r"""The nightly job: wipe the derived caches, then re-download today's data.

One entry point so Task Scheduler has one action and the order is guaranteed --
warming before the wipe would just delete what it had fetched.

    conda run -n mfa_env python scripts/nightly.py          # DRY RUN, no delete
    conda run -n mfa_env python scripts/nightly.py --yes    # the real thing

Registered as \AgenticOS\sst_viewer_nightly; see scripts/register_nightly.ps1.
"""

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import cleanup_cache  # noqa: E402
import warm_cache     # noqa: E402


class _Tee:
    """Mirror stdout/stderr into cache/nightly.log.

    The scheduled task used to get its logging from a `cmd.exe /c ... >> log`
    wrapper. That wrapper failed with 0xC0000142 (DLL init) when the task fired
    on wake rather than at its scheduled time, so the job silently did nothing
    and left no trace. Logging from inside Python means the task can invoke
    python.exe directly -- one less process that has to start correctly at 3am.
    """

    def __init__(self, stream, fh):
        self._s, self._f = stream, fh

    def write(self, data):
        self._s.write(data)
        self._f.write(data)
        self._f.flush()

    def flush(self):
        self._s.flush()
        self._f.flush()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    yes = "--yes" in argv
    log = cleanup_cache.CACHE / "nightly.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    fh = open(log, "a", encoding="utf-8")
    sys.stdout = _Tee(sys.stdout, fh)
    sys.stderr = _Tee(sys.stderr, fh)
    print(f"=== sst_viewer nightly {time.strftime('%Y-%m-%d %H:%M:%S')} ===",
          flush=True)

    rc = cleanup_cache.main(["--yes"] if yes else [])
    if rc:
        print("cleanup reported a problem; warming anyway", flush=True)
    if not yes:
        print("dry run: skipping the download step too "
              "(it would fetch ~80 MB). Pass --yes to run for real.", flush=True)
        return 0

    # The wipe just removed today's fields, so this is what makes the morning
    # launch instant instead of a multi-minute download.
    return warm_cache.main([a for a in argv if a != "--yes"])


if __name__ == "__main__":
    sys.exit(main())
