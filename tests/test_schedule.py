"""The lock, which is the only part of scheduling a laptop can do honestly.

Two cycles running at once would interleave writes to the same snapshot files
and append to the same journal. The damage is not a crash: it is a corner whose
baseline is half of one sweep and half of another, producing a delta that never
happened, journaled with confident reasoning. A scheduled job that can overlap
with a hand run is not a schedule, it is a race.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from corner_watchdog.cli import main as cli_main
from corner_watchdog.schedule import (
    LOCK_NAME,
    CycleAlreadyRunning,
    crontab_line,
    cycle_lock,
    install_instructions,
    plist,
    read_lock,
)


def test_the_lock_is_held_then_released(tmp_path):
    with cycle_lock(tmp_path):
        assert (tmp_path / LOCK_NAME).exists()
    assert not (tmp_path / LOCK_NAME).exists()


def test_the_lock_records_who_holds_it(tmp_path):
    with cycle_lock(tmp_path):
        held = read_lock(tmp_path)
        assert held["pid"] == os.getpid()
        assert held["started"]
        assert held["host"]


def test_a_second_cycle_is_refused_while_the_first_runs(tmp_path):
    with cycle_lock(tmp_path), pytest.raises(CycleAlreadyRunning) as e, cycle_lock(tmp_path):
        raise AssertionError("the second cycle should never have got in")
    assert "still running" in str(e.value)


def test_the_lock_is_released_even_when_the_cycle_raises(tmp_path):
    """A crashed cycle must not wedge the schedule until somebody notices."""
    with pytest.raises(ValueError), cycle_lock(tmp_path):
        raise ValueError("the sweep blew up")
    assert not (tmp_path / LOCK_NAME).exists()


def test_a_lock_held_by_a_dead_process_is_broken(tmp_path):
    (tmp_path).mkdir(parents=True, exist_ok=True)
    # A pid that cannot be alive. Pid 0 is not a real user process to signal.
    (tmp_path / LOCK_NAME).write_text(json.dumps({"pid": 999999, "started": "old", "host": "gone"}))
    with cycle_lock(tmp_path):
        assert read_lock(tmp_path)["pid"] == os.getpid()
    assert "broke a stale lock" in (tmp_path / "locks.log").read_text()


def test_a_lock_older_than_the_stale_window_is_broken(tmp_path):
    (tmp_path / LOCK_NAME).write_text(json.dumps({"pid": os.getpid(), "started": "old", "host": "h"}))
    # Same live pid, so only age can break it.
    with cycle_lock(tmp_path, stale_after=0):
        assert read_lock(tmp_path)["pid"] == os.getpid()
    assert "broke a stale lock" in (tmp_path / "locks.log").read_text()


def test_a_corrupt_lock_file_is_broken_rather_than_wedging_forever(tmp_path):
    (tmp_path / LOCK_NAME).write_text("{not json at all")
    with cycle_lock(tmp_path):
        assert read_lock(tmp_path)["pid"] == os.getpid()


def test_lock_breaking_is_recorded_outside_the_decision_journal(tmp_path):
    """Machine noise must not inflate the denominator of the restraint rate."""
    (tmp_path / LOCK_NAME).write_text(json.dumps({"pid": 999999, "started": "old", "host": "g"}))
    with cycle_lock(tmp_path):
        pass
    assert (tmp_path / "locks.log").exists()
    assert not (tmp_path / "journal.jsonl").exists()


# --------------------------------------------------------------- the rendering

def test_the_plist_runs_tick_not_run(tmp_path):
    """`run` has no lock. A scheduler must never be pointed at it."""
    xml = plist(repo=Path("/repo"), python=Path("/py"), hour_interval=6)
    assert "<string>tick</string>" in xml
    assert "<string>run</string>" not in xml
    assert "<integer>21600</integer>" in xml


def test_the_plist_does_not_fire_on_load():
    """Otherwise every laptop wake becomes a burst against DataSF."""
    xml = plist(repo=Path("/repo"), python=Path("/py"))
    assert "<key>RunAtLoad</key><false/>" in xml


def test_the_crontab_line_changes_directory_first():
    line = crontab_line(repo=Path("/repo"), python=Path("/py"), hour_interval=6)
    assert line.startswith("0 */6 * * * cd /repo &&")
    assert "watchdog tick" in line


def test_the_instructions_say_nothing_was_installed():
    text = "\n".join(install_instructions(plist_path=Path("/x.plist")))
    assert "Nothing has been installed" in text
    assert "launchctl unload" in text  # the way out is documented beside the way in


def test_schedule_command_writes_config_and_installs_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "ops" / "job.plist"
    code = cli_main(["schedule", "--schedule-out", str(out), "--every-hours", "4"])
    printed = capsys.readouterr().out
    assert code == 0
    assert out.exists()
    assert "<integer>14400</integer>" in out.read_text()
    assert "Nothing has been installed" in printed
    # It must not have touched the real LaunchAgents directory.
    assert not (Path.home() / "Library" / "LaunchAgents" / "dev.watchdog.cycle.plist").exists()


# ------------------------------------------------ the lock covers both entrypoints

def test_a_hand_started_run_also_takes_the_lock(tmp_path, capsys):
    """Found by auditing a documentation claim rather than by reading the code.

    The FAQ said a scheduled run can never overlap with one started by hand. Only
    `tick` took the lock, so the promise held in one direction and missed the
    interesting collision: somebody running this while the six-hourly job is
    mid-sweep.
    """
    from corner_watchdog.cli import main

    with cycle_lock(tmp_path):
        code = main(["--state", str(tmp_path), "run", "--cycles", "1"])
    out = capsys.readouterr().out
    assert code == 4
    assert "Refusing to start" in out
    assert "interleave writes" in out


def test_both_entrypoints_use_the_same_lock_file(tmp_path):
    """One lock, or the guarantee is only about whichever ran second."""
    import inspect

    from corner_watchdog import cli

    for fn in (cli._cmd_run, cli._cmd_tick):
        assert "cycle_lock" in inspect.getsource(fn), f"{fn.__name__} does not take the lock"


def test_a_run_releases_the_lock_so_the_next_one_can_start(tmp_path, monkeypatch, capsys):
    from corner_watchdog.cli import main

    watched = tmp_path / "watched.json"
    watched.write_text(json.dumps({"roster_hash": "x", "corners": []}))
    for _ in range(2):
        code = main(["--state", str(tmp_path), "--watched", str(watched),
                     "--ledger", str(tmp_path / "l.html"), "run", "--cycles", "1"])
        assert code == 0
    assert not (tmp_path / LOCK_NAME).exists()
