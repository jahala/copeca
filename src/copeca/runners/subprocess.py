"""Subprocess runner — spawns CLI agent with process-group isolation.

Architecture: adapter. Implements BaseRunner with real subprocess execution.
"""

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field

from copeca.config.models import IsolationSpec
from copeca.runners.base import BaseRunner
from copeca.runners.parsers.base import Parser, RunResult

# ── Env allowlist ─────────────────────────────────────────────────────────────
#
# The child process inherits ONLY these keys from the host environment.
# Everything else (CLAUDECODE, CLAUDE_*, MCP_*, arbitrary ambient hooks) is
# excluded so the baseline arm is never contaminated by the host's tooling.
#
# Infra vars: the process needs a working shell environment.
# Locale vars: matched by the LC_* prefix in _build_child_env — non-ASCII
#              repos need them.
# Provider credentials: real agent runs need the API key and optional overrides.
BASE_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        # Infra — shell / process environment
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "TERM",
        "TMPDIR",
        "TZ",
        # Provider credentials
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    }
)


def _build_child_env(
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build an explicit, minimal child environment from the host.

    Copies host vars whose key is in BASE_ENV_ALLOWLIST or starts with ``LC_``
    (locale). Merges *extra* on top — explicit env wins over any allowlisted
    host value. Everything else (CLAUDECODE, CLAUDE_*, MCP_*, etc.) is dropped.

    Args:
        extra: Additional key-value pairs to merge (e.g. mode.env overrides).

    Returns:
        A new dict to pass as ``env=`` to subprocess.Popen.
    """
    env: dict[str, str] = {
        k: v for k, v in os.environ.items() if k in BASE_ENV_ALLOWLIST or k.startswith("LC_")
    }
    if extra:
        env.update(extra)
    return env


# ── Process-group registry ──────────────────────────────────────────────────
#
# Each agent runs in its own process group (os.setsid in run() below). While a
# run is in flight its group id is registered here so the CLI's SIGINT/SIGTERM
# handler can group-kill every live agent on interruption — leaving no orphaned
# agent or MCP-server children (RUN-E). The registry is process-wide and
# thread-safe because run_matrix dispatches runs across a thread pool.
_active_pgids: set[int] = set()
_active_pgids_lock = threading.Lock()


def _register_pgid(pgid: int) -> None:
    """Record a live agent process group."""
    with _active_pgids_lock:
        _active_pgids.add(pgid)


def _unregister_pgid(pgid: int) -> None:
    """Drop a process group once its run has finished."""
    with _active_pgids_lock:
        _active_pgids.discard(pgid)


def terminate_active_process_groups(sig: int = signal.SIGTERM) -> list[int]:
    """Signal every currently-registered agent process group (best-effort).

    Called by the CLI interrupt handler so an aborted run leaves no orphaned
    agent / MCP-server processes. Groups that already exited are skipped.

    Args:
        sig: Signal to send (SIGTERM by default; the interrupt handler uses
             SIGKILL for an immediate, no-hang abort).

    Returns:
        The list of process-group ids that were signalled.
    """
    with _active_pgids_lock:
        pgids = list(_active_pgids)
    signalled: list[int] = []
    for pgid in pgids:
        try:
            os.killpg(pgid, sig)
            signalled.append(pgid)
        except ProcessLookupError:
            pass  # group already gone
    return signalled


@dataclass
class SubprocessRunner(BaseRunner):
    """Run a CLI agent as a subprocess with process-group isolation."""

    timeout: int = 300
    parser: Parser | None = field(default=None)
    config_dir_env: str | None = (
        None  # env var name to deliver per-arm config dir (e.g. "CLAUDE_CONFIG_DIR")
    )
    isolation: IsolationSpec | None = field(default=None)  # per-CLI clean-room descriptor

    def run(
        self,
        command: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> RunResult:
        """Execute the command and return a parsed RunResult.

        Args:
            command: The full CLI command as a list of strings.
            cwd: Optional working directory for the subprocess.
            env: Optional extra env vars to merge on top of the allowlist
                 (e.g. mode.env from provision_arm). Keys in *env* override
                 any allowlisted host value.

        Returns:
            Parsed RunResult from the agent's output.
        """
        # Build an explicit, minimal child env from the strict allowlist;
        # merge any explicit overrides last (side effects at the I/O boundary).
        child_env = _build_child_env(env)

        start = time.perf_counter()

        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,  # codex reads its prompt from stdin if piped;
            # hand every child an empty stdin so a stdin-reading agent gets immediate
            # EOF and never blocks on the orchestrator's inherited stdin (SD-L).
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=child_env,
            preexec_fn=os.setsid,  # Create new process group
        )

        # Register the group so the CLI interrupt handler can kill it if the run
        # is aborted mid-flight (RUN-E). Captured once: a fast-exiting child may
        # already be gone, in which case there is nothing to track or kill.
        try:
            pgid: int | None = os.getpgid(process.pid)
        except ProcessLookupError:
            pgid = None
        if pgid is not None:
            _register_pgid(pgid)

        try:
            try:
                stdout, stderr = process.communicate(timeout=self.timeout)
                duration_ms = int((time.perf_counter() - start) * 1000)
            except subprocess.TimeoutExpired:
                # Kill the entire process group (agent + any children / MCP servers).
                if pgid is not None:
                    os.killpg(pgid, signal.SIGKILL)
                process.wait()
                raise

            returncode = process.returncode

            if self.parser:
                result = self.parser.parse(stdout)
            else:
                result = RunResult(result_text=stdout)
            result.duration_ms = duration_ms
            result.exit_code = returncode

            # Surface execution failures the parser can't see. A non-zero exit, or
            # empty stdout with stderr diagnostics, means the agent did not run to
            # completion — record it as an error so the run is never mistaken for a
            # legitimate empty answer (shakedown SD-B). Don't clobber an error the
            # parser already set.
            if result.error is None and (
                returncode != 0 or (not stdout.strip() and stderr.strip())
            ):
                stderr_tail = stderr.strip()[-500:]
                detail = f": {stderr_tail}" if stderr_tail else ""
                result.error = f"runner exited with code {returncode}{detail}"

            return result
        finally:
            # Run finished (or timed out + killed): the group is no longer live.
            if pgid is not None:
                _unregister_pgid(pgid)

    def parse(self, stdout: str, supported_events: list[str] | None = None) -> RunResult:
        """Not used directly — the parser is injected and called from run()."""
        if self.parser:
            return self.parser.parse(stdout, supported_events)
        return RunResult(result_text=stdout)
