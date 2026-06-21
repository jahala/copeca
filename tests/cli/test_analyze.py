"""Test `copeca analyze` CLI command end-to-end."""

import json
import subprocess


def copeca(*args):
    """Run copeca CLI via the installed entry point and return CompletedProcess."""
    return subprocess.run(
        ["copeca", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestAnalyzeCli:
    def test_analyze_valid_jsonl_exits_zero(self, tmp_path):
        """copeca analyze on valid JSONL produces markdown, exits 0."""
        jl = tmp_path / "results.jsonl"
        jl.write_text('{"task":"a","correct":true,"total_cost_usd":0.05,"mode":"baseline"}\n')
        result = copeca("analyze", str(jl))
        assert result.returncode == 0
        assert "Cost Per Correct" in result.stdout

    def test_analyze_format_json(self, tmp_path):
        """--format json produces valid JSON with cost_per_correct."""
        jl = tmp_path / "results.jsonl"
        jl.write_text('{"task":"a","correct":true,"total_cost_usd":0.05,"mode":"baseline"}\n')
        result = copeca("analyze", str(jl), "--format", "json")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "cost_per_correct" in data
        assert data["num_records"] == 1

    def test_analyze_empty_jsonl_exits_one(self, tmp_path):
        """Empty file -> exit 1 with error message."""
        jl = tmp_path / "empty.jsonl"
        jl.write_text("")
        result = copeca("analyze", str(jl))
        assert result.returncode == 1

    def test_analyze_nonexistent_file_exits_two(self, tmp_path):
        """Missing file -> exit 2."""
        result = copeca("analyze", str(tmp_path / "nope.jsonl"))
        assert result.returncode == 2

    def test_analyze_output_flag_writes_file(self, tmp_path):
        """-o writes report to file."""
        jl = tmp_path / "results.jsonl"
        jl.write_text('{"task":"a","correct":true,"total_cost_usd":0.05,"mode":"baseline"}\n')
        out = tmp_path / "report.md"
        result = copeca("analyze", str(jl), "-o", str(out))
        assert result.returncode == 0
        assert out.exists()
        assert "Cost Per Correct" in out.read_text()
