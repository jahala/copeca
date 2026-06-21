"""F-M4: _run_setup_commands must NOT use shell=True (shell injection guard).

Engineering.md §4: subprocess must use argv form, no shell features.

The test proves injection is neutralised: a setup command containing a shell
metacharacter (`;`) does NOT execute the second shell statement when shell=False
— the `;` is treated as a literal argument to the program, not a separator.
"""

from pathlib import Path

import pytest

from copeca.orchestration.state import _run_setup_commands


class TestSetupCommandShellInjection:
    def test_semicolon_does_not_create_injected_file(self, tmp_path: Path) -> None:
        """Shell metacharacter `;` in a setup command must NOT be interpreted.

        Under shell=True, `echo hi; touch /tmp/INJECTED` runs two commands.
        Under shell=False (argv), `shlex.split` splits the string into tokens and
        `touch` with `;` as an argument is never reached — only `echo` runs.
        The INJECTED sentinel file must NOT be created.
        """
        injected = tmp_path / "INJECTED"

        # This command embeds a shell injection attempt via `;`
        injection_cmd = f"echo hi; touch {injected}"

        # Must not raise (echo is a valid command)
        _run_setup_commands([injection_cmd], cwd=tmp_path)

        assert not injected.exists(), (
            "Shell injection via `;` must be neutralised: INJECTED file must not be created. "
            "This means shell=True is still active in _run_setup_commands."
        )

    def test_valid_command_still_runs(self, tmp_path: Path) -> None:
        """A simple argv-safe command (no shell features) must execute normally."""
        sentinel = tmp_path / "sentinel.txt"
        _run_setup_commands([f"touch {sentinel}"], cwd=tmp_path)

        assert sentinel.exists(), "A plain `touch <file>` command must succeed under argv form."

    def test_failed_command_raises_runtime_error(self, tmp_path: Path) -> None:
        """A command that exits non-zero must still raise RuntimeError."""
        with pytest.raises(RuntimeError, match="failed with exit code"):
            _run_setup_commands(["false"], cwd=tmp_path)
