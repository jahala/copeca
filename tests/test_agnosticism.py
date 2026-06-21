"""Tool-agnosticism lint — task text must name the demand, not the method."""

from copeca.agnosticism import check_tool_agnostic
from copeca.config.loader import load_tasks_from_dir
from copeca.config.resources import data_path


class TestToolAgnostic:
    def test_clean_task_passes(self):
        assert (
            check_tool_agnostic(
                "gin_new_constructor",
                "Report gin's New() constructor: its return type, the fields it "
                "initializes, the helpers it calls, and roughly how many callers it has.",
                "Map gin.New and its neighborhood; tests construction tracing.",
            )
            == []
        )

    def test_flags_experimental_tool_names(self):
        assert check_tool_agnostic("t", "Use tilth to find the trait.", "")
        assert check_tool_agnostic("grok_gin_new", "Find the New constructor.", "")
        assert check_tool_agnostic("t", "Run ctags and report the symbol.", "")

    def test_flags_single_shot_aggregator_priming(self):
        # the exact grok couplings
        assert check_tool_agnostic(
            "t", "Describe New(). One structured answer beats several searches.", ""
        )
        assert check_tool_agnostic(
            "t", "Show Depends. One structured answer is better than several partial ones.", ""
        )
        assert check_tool_agnostic(
            "t", "Show Context.Next. I want one consolidated view, not piecemeal searches.", ""
        )

    def test_flags_method_prescription(self):
        assert check_tool_agnostic("t", "Grep for the Matcher trait.", "")
        assert check_tool_agnostic("t", "Use your search tool to locate it.", "")

    def test_repo_name_is_allowed_as_subject(self):
        # ripgrep/gin/express/fastapi are SUBJECTS, never flagged
        assert (
            check_tool_agnostic(
                "t", "In the ripgrep codebase, find the Matcher trait and its implementors.", ""
            )
            == []
        )

    def test_search_as_domain_subject_not_flagged(self):
        # 'search' is ripgrep's whole point — flagging it would be a false positive
        assert (
            check_tool_agnostic(
                "t", "Trace ripgrep's search worker as it coordinates across threads.", ""
            )
            == []
        )
        assert (
            check_tool_agnostic(
                "t", "Trace the search execution flow from main() to the first match.", ""
            )
            == []
        )


class TestPackagedTasksAgnostic:
    def test_all_packaged_tasks_are_tool_agnostic(self):
        tasks = load_tasks_from_dir(data_path("tasks"))
        assert len(tasks) >= 16
        for t in tasks:
            violations = check_tool_agnostic(t.name, t.prompt, t.description)
            assert violations == [], f"{t.name} is tool-coupled: {violations}"
