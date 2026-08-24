"""Running on a schedule, on this laptop, with nothing in the cloud.

Cloud Scheduler gives the deployed design three things: it fires on time, it
never fires twice at once, and it leaves a record when a run is skipped. Only
the last two can be reproduced honestly by a laptop, so those are what this
provides, and the firing is left to launchd or cron.

The lock is the part that matters. Two cycles running at once would interleave
writes to the same snapshot files and append to the same journal, and the damage
would be a corner whose baseline is half of one sweep and half of another, which
produces a delta that never happened. A scheduled job that can overlap with a
hand run is not a scheduled job, it is a race.

Nothing here installs anything. `plist` and `crontab_line` render the
configuration and print the command that would install it, because a background
job that appears on somebody's machine without them typing the command is a
surprise, and this repo is an argument against surprises.
"""

from __future__ import annotations

import datetime as _dt
import errno
import json
import os
import socket
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

LOCK_NAME = "cycle.lock"
LOCK_LOG = "locks.log"

# A sweep of 25 corners takes about seven seconds. An hour is far past any
# honest run and comfortably short of the six hour interval, so a lock older
# than this belonged to a process that died without cleaning up.
STALE_AFTER_SECONDS = 3600

LABEL = "dev.watchdog.cycle"


class CycleAlreadyRunning(RuntimeError):
    """Another cycle holds the lock. Not an error, a correct refusal."""


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as e:
        return e.errno == errno.EPERM  # exists but owned by someone else
    return True


def _note(state_dir: Path, message: str) -> None:
    """Operational events go here, never into the decision journal.

    The journal is a record of what the agent decided about street corners. A
    lock that went stale is a fact about this laptop, and mixing the two would
    let machine noise inflate the denominator of the restraint rate.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
    with (state_dir / LOCK_LOG).open("a") as fh:
        fh.write(f"{stamp} {message}\n")


def read_lock(state_dir: str | os.PathLike[str] = "state") -> dict | None:
    path = Path(state_dir) / LOCK_NAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"pid": None, "started": None, "corrupt": True}


@contextmanager
def cycle_lock(
    state_dir: str | os.PathLike[str] = "state", *, stale_after: int = STALE_AFTER_SECONDS
) -> Iterator[Path]:
    """Hold the right to run a cycle, or refuse.

    Raises CycleAlreadyRunning when a live cycle holds it. Breaks a lock whose
    owner is gone or which is older than `stale_after`, and records the break,
    because a scheduled job that wedges permanently after one crash is worse
    than one that occasionally overlaps.
    """
    root = Path(state_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / LOCK_NAME
    payload = json.dumps(
        {
            "pid": os.getpid(),
            "started": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
            "host": socket.gethostname(),
        }
    )

    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        held = read_lock(root) or {}
        pid = held.get("pid")
        age = _lock_age_seconds(path)
        stale = bool(held.get("corrupt")) or age > stale_after or (pid and not _pid_alive(int(pid)))
        if not stale:
            raise CycleAlreadyRunning(  # noqa: B904 - a held lock is a state, not a wrapped error
                f"a cycle started at {held.get('started')} by pid {pid} is still running"
            )
        _note(root, f"broke a stale lock held by pid {pid}, age {int(age)}s")
        path.unlink(missing_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)

    try:
        os.write(fd, payload.encode())
        os.close(fd)
        yield path
    finally:
        path.unlink(missing_ok=True)


def _lock_age_seconds(path: Path) -> float:
    try:
        # time.time() rather than a naive datetime: this is a duration against a
        # filesystem mtime, and a local-time clock would jump an hour at a DST
        # boundary and either wedge the lock or break it early.
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return float("inf")


# ------------------------------------------------------------- configuration

def plist(
    *, repo: Path, python: Path, hour_interval: int = 6, label: str = LABEL
) -> str:
    """A launchd user agent. Rendered, never installed."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string>
    <string>-m</string>
    <string>corner_watchdog</string>
    <string>tick</string>
  </array>
  <key>WorkingDirectory</key><string>{repo}</string>
  <key>StartInterval</key><integer>{hour_interval * 3600}</integer>
  <!-- Deliberately false. A cycle that fires the moment the laptop wakes,
       every time, turns a schedule into a burst and spends DataSF's
       goodwill for nothing. Missing a window is fine; the next one
       compares against the same stored baseline either way. -->
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>{repo}/state/schedule.out.log</string>
  <key>StandardErrorPath</key><string>{repo}/state/schedule.err.log</string>
</dict>
</plist>
"""


def crontab_line(*, repo: Path, python: Path, hour_interval: int = 6) -> str:
    return f"0 */{hour_interval} * * * cd {repo} && {python} -m watchdog tick >> state/schedule.out.log 2>&1"


def install_instructions(*, plist_path: Path, label: str = LABEL) -> list[str]:
    """The exact commands, for a person to run, having read them."""
    return [
        "This installs a background job on this machine. Nothing has been installed.",
        "",
        "  launchd, macOS:",
        f"    cp {plist_path} ~/Library/LaunchAgents/{label}.plist",
        f"    launchctl load ~/Library/LaunchAgents/{label}.plist",
        "",
        "  to remove it:",
        f"    launchctl unload ~/Library/LaunchAgents/{label}.plist",
        f"    rm ~/Library/LaunchAgents/{label}.plist",
        "",
        "  cron, anywhere:  crontab -e, then paste the line printed above.",
        "",
        "Either way the job runs `watchdog tick`, which takes the cycle lock and",
        "refuses rather than overlapping with a run you started by hand.",
    ]


def default_python() -> Path:
    return Path(sys.executable)
