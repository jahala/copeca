"""RUN-E: child-process cleanup — process-group registry, group-kill, no orphans.

Three discriminating tests:
(1) terminate_active_process_groups kills every registered group AND its children
    (the no-orphan mechanism the CLI interrupt handler relies on).
(2) SubprocessRunner.run registers its process group DURING the run and clears it
    after (so an interrupt mid-run finds the live group to kill).
(3) a timed-out run group-kills the whole group — a forked child does not survive
    as an orphan (copeca-single-run c004).
"""

from __future__ import annotations

import os
import signal
import subprocess
import time

import pytest

from copeca.runners.parsers.base import RunResult
from copeca.runners.subprocess import (
    SubprocessRunner,
    _active_pgids,
    _register_pgid,
    _unregister_pgid,
    terminate_active_process_groups,
)


class _NullParser:
    def parse(self, stdout, supported_events=None):
        return RunResult(result_text=stdout, total_cost_usd=0.0, duration_ms=0)


class _RegistryProbeParser:
    """Records how many groups are registered at parse time (i.e. during the run)."""

    def __init__(self) -> None:
        self.registered_during_run: int | None = None

    def parse(self, stdout, supported_events=None):
        self.registered_during_run = len(_active_pgids)
        return RunResult(result_text=stdout, total_cost_usd=0.0, duration_ms=0)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def test_terminate_kills_registered_groups_and_their_children():
    """terminate_active_process_groups SIGKILLs every registered group + children.

    DISCRIMINATES: a child forked into the group is also killed — this is the
    no-orphan guarantee. Would fail if terminate signalled only the leader pid.
    """
    # sh (-c, no job control) keeps the backgrounded sleep in the SAME group.
    proc = subprocess.Popen(
        ["sh", "-c", "sleep 30 & sleep 30"],
        start_new_session=True,  # own session+group, like the real runner's os.setsid
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pgid = os.getpgid(proc.pid)
    _register_pgid(pgid)
    try:
        signalled = terminate_active_process_groups(signal.SIGKILL)
        assert pgid in signalled

        proc.wait(timeout=5)
        assert proc.poll() is not None  # leader dead

        # The whole group is gone: signalling it raises ProcessLookupError.
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                os.killpg(pgid, 0)
                time.sleep(0.05)
            except ProcessLookupError:
                break
        else:
            pytest.fail(f"process group {pgid} (with children) survived the kill")
    finally:
        _unregister_pgid(pgid)
        with __import__("contextlib").suppress(ProcessLookupError):
            os.killpg(pgid, signal.SIGKILL)


def test_run_registers_pgid_during_run_and_clears_after():
    """run() registers its group while the agent runs and deregisters when done.

    DISCRIMINATES: registered_during_run must be >= 1 (the interrupt handler can
    only kill a group that is registered while it's live); and the registry must
    be empty after, so finished runs aren't killed by a later interrupt.
    """
    probe = _RegistryProbeParser()
    runner = SubprocessRunner(
        name="echo-test",
        cli="echo",
        default_args=[],
        arg_map={"prompt_separator": ""},
        parser=probe,
    )
    before = len(_active_pgids)
    runner.run(["echo", "hi"])
    assert probe.registered_during_run is not None
    assert probe.registered_during_run >= before + 1  # registered during the run
    assert len(_active_pgids) == before  # cleared after


def test_timeout_group_kills_children_no_orphan(tmp_path):
    """A timed-out run SIGKILLs the whole group — a forked child does not orphan.

    Satisfies copeca-single-run c004. DISCRIMINATES: if only the direct child were
    killed (not the group), the backgrounded grandchild would survive.
    """
    pidfile = tmp_path / "child.pid"
    # Background a child sleep, record its PID, then the parent sleeps past timeout.
    script = f"sleep 30 & echo $! > {pidfile}; sleep 30"
    runner = SubprocessRunner(
        name="sh-test",
        cli="sh",
        default_args=["-c"],
        arg_map={"prompt_separator": ""},
        parser=_NullParser(),
        timeout=1,
    )

    with pytest.raises(subprocess.TimeoutExpired):
        runner.run(["sh", "-c", script])

    child_pid = int(pidfile.read_text().strip())
    deadline = time.time() + 5
    while _alive(child_pid) and time.time() < deadline:
        time.sleep(0.05)
    assert not _alive(child_pid), f"orphan: child {child_pid} survived the timeout group-kill"
