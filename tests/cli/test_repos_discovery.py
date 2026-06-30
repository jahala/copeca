"""repos.yaml discovery for `copeca run`: cwd -> task-sibling -> bundled corpus.

The bundled-corpus fallback is what lets the shipped tasks (e.g. the verbatim
SWE-bench-Live tasks) resolve their repo URLs out of the box, with no local
repos.yaml — previously a first-ever run of a bundled repo failed with
"No bare clone ... and no uri provided".
"""

from pathlib import Path

from copeca.cli import _discover_repos_path
from copeca.config.loader import load_repos
from copeca.config.resources import data_path


def test_falls_back_to_bundled_corpus(tmp_path: Path) -> None:
    # No repos.yaml in cwd or beside the task -> the bundled corpus repos.yaml.
    task = tmp_path / "tasks" / "ripgrep" / "some_task.yaml"
    resolved = _discover_repos_path(task, cwd=tmp_path)
    assert resolved == data_path("repos.yaml")
    assert "ripgrep" in load_repos(resolved)


def test_prefers_cwd_repos(tmp_path: Path) -> None:
    (tmp_path / "repos.yaml").write_text("ripgrep: {}\n")
    assert _discover_repos_path(tmp_path / "x.yaml", cwd=tmp_path) == tmp_path / "repos.yaml"


def test_prefers_task_sibling_over_bundled(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    (corpus / "tasks").mkdir(parents=True)
    sibling = corpus / "repos.yaml"
    sibling.write_text("ripgrep: {}\n")
    task = corpus / "tasks" / "t.yaml"
    assert _discover_repos_path(task, cwd=tmp_path) == sibling
