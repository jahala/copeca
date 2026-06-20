"""Subprocess runner — spawns CLI agent with process-group isolation.

Architecture: adapter. Implements BaseRunner with real subprocess execution.
"""

import os
import signal
import subprocess
import time
from dataclasses import dataclass, field

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
BASE_ENV_ALLOWLIST: frozenset[str] = frozenset({
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
})


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
        k: v
        for k, v in os.environ.items()
        if k in BASE_ENV_ALLOWLIST or k.startswith("LC_")
    }
    if extra:
        env.update(extra)
    return env


@dataclass
class SubprocessRunner(BaseRunner):
    """Run a CLI agent as a subprocess with process-group isolation."""

    timeout: int = 300
    parser: Parser | None = field(default=None)
    config_dir_env: str | None = None  # env var name to deliver per-arm config dir (e.g. "CLAUDE_CONFIG_DIR")

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
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=child_env,
            preexec_fn=os.setsid,  # Create new process group
        )

        try:
            stdout, stderr = process.communicate(timeout=self.timeout)
            duration_ms = int((time.perf_counter() - start) * 1000)
        except subprocess.TimeoutExpired:
            # Kill the entire process group
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            process.wait()
            raise

        if self.parser:
            result = self.parser.parse(stdout)
            result.duration_ms = duration_ms
            return result

        return RunResult(
            result_text=stdout,
            duration_ms=duration_ms,
        )

    def parse(self, stdout: str, supported_events: list[str] | None = None) -> RunResult:
        """Not used directly — the parser is injected and called from run()."""
        if self.parser:
            return self.parser.parse(stdout, supported_events)
        return RunResult(result_text=stdout)
