"""Performance gate: validate 50 tasks must complete in under 500ms."""

import subprocess
import time


class TestValidatePerformance:
    def test_validate_50_tasks_under_500ms(self, tmp_path):
        """Generate 50 valid YAML tasks and run copeca validate."""
        tasks_dir = tmp_path / "perf_tasks"
        tasks_dir.mkdir()

        for i in range(50):
            task_yaml = f"""name: perf_test_{i}
source: "SWE-QA (Apache-2.0)"
repo: ripgrep
type: comprehension
language: rust
difficulty: easy
version: 1
prompt: "Performance test task {i}"
ground_truth:
  required_strings:
    - test_{i}
"""
            (tasks_dir / f"task_{i:03d}.yaml").write_text(task_yaml)

        start = time.perf_counter()
        result = subprocess.run(
            ["copeca", "validate", str(tasks_dir)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result.returncode == 0, f"exit {result.returncode}: {result.stderr}"
        assert elapsed_ms < 500, f"validate took {elapsed_ms:.0f}ms, must be < 500ms"
