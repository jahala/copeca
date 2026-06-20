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


@dataclass
class SubprocessRunner(BaseRunner):
    """Run a CLI agent as a subprocess with process-group isolation."""

    timeout: int = 300
    parser: Parser | None = field(default=None)
    def run(self, command: list[str], cwd: str | None = None) -> RunResult:
        """Execute the command and return a parsed RunResult.

        Args:
            command: The full CLI command as a list of strings.
            cwd: Optional working directory for the subprocess.

        Returns:
            Parsed RunResult from the agent's output.
        """
        # Filter env — remove CLAUDECODE to allow nested claude -p
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        start = time.perf_counter()

        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
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
