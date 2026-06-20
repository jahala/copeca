"""Domain model dataclasses for copeca — Pydantic v2, pure data, no I/O.

Architecture invariant (§7): this file must never import from runners/,
repos/, results/, or orchestration/. It is mechanically enforceable in CI.
"""

from enum import Enum

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

# ── Enums ─────────────────────────────────────────────────────────────────────


class TaskType(str, Enum):
    comprehension = "comprehension"
    edit = "edit"


class Language(str, Enum):
    python = "python"
    rust = "rust"
    go = "go"
    javascript = "javascript"


class Difficulty(str, Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class MutationAction(Enum):
    replace = "replace"
    delete = "delete"
    insert_after = "insert_after"
    create = "create"




# ── Ground truth (discriminated: comprehension vs edit) ───────────────────────


class BaseGroundTruth(BaseModel):
    """Base for discriminated ground truth types."""

    required_strings: list[str] = Field(default_factory=list)
    forbidden_strings: list[str] = Field(default_factory=list)


class ComprehensionGroundTruth(BaseGroundTruth):
    """Comprehension tasks: strings only. Correct = required AND all_of AND forbidden."""

    all_of: list[str] = Field(default_factory=list)


class EditGroundTruth(BaseGroundTruth):
    """Edit tasks: test_command is authoritative. Strings are diagnostic only."""

    test_command: list[str] = Field(default_factory=list)


GroundTruth = ComprehensionGroundTruth | EditGroundTruth


# ── Mutation ──────────────────────────────────────────────────────────────────


class Mutation(BaseModel):
    """A single file mutation to introduce or fix a bug."""

    file: str = Field(..., min_length=1)
    action: MutationAction = MutationAction.replace
    find: str = ""
    replace: str = ""
    content: str = ""
    occurrence: int | None = None

    @field_validator("find")
    @classmethod
    def find_required_for_search_actions(cls, v: str, info: 'ValidationInfo') -> str:
        action = info.data.get("action", MutationAction.replace)
        if action in (MutationAction.replace, MutationAction.delete, MutationAction.insert_after):
            if not v:
                raise ValueError(f"find is required for action '{action.value}'")
        return v

    @field_validator("content")
    @classmethod
    def content_required_for_create_and_insert(cls, v: str, info: 'ValidationInfo') -> str:
        action = info.data.get("action", MutationAction.replace)
        if action in (MutationAction.create, MutationAction.insert_after):
            if not v:
                raise ValueError(f"content is required for action '{action.value}'")
        return v


# ── Task ──────────────────────────────────────────────────────────────────────


class Task(BaseModel):
    """A benchmark task — data, never code (design decision #15)."""

    name: str = Field(..., min_length=1, pattern=r"^[a-z][a-z0-9_-]*$")
    description: str = ""
    source: str = Field(..., min_length=1)
    repo: str = Field(..., min_length=1)
    type: TaskType
    language: Language
    difficulty: Difficulty
    version: int = Field(default=1, ge=1)
    prompt: str = Field(..., min_length=1)
    ground_truth: GroundTruth
    mutations: list[Mutation] = Field(default_factory=list)


# ── Repo ──────────────────────────────────────────────────────────────────────


class Repo(BaseModel):
    """A pinned repository reference — URL, commit, toolchain, setup."""

    url: str = Field(..., min_length=1)
    commit: str = Field(..., min_length=1)
    language: Language
    toolchain: dict[str, str] = Field(default_factory=dict)
    setup_command: list[str] = Field(default_factory=list)


# ── Mode ──────────────────────────────────────────────────────────────────────


class Mode(BaseModel):
    """A benchmark mode — how a tool attaches to the agent for A/B comparison.

    At least one integration path must be specified. Multiple paths
    may be combined (e.g. MCP + env for proxied MCP servers).
    """

    name: str = Field(..., min_length=1, pattern=r"^[a-z][a-z0-9_-]*$")
    description: str = ""
    tools: list[str] = Field(default_factory=list)
    mcp_config: dict[str, object] | None = None
    env: dict[str, str] | None = None
    agent_config: str | None = None
    wrapper: list[str] | None = None
    setup: list[str] | None = None

    @model_validator(mode="after")
    def at_least_one_path_or_tool_change(self) -> "Mode":
        """Validate that at least one integration path is specified."""
        if not any(
            [
                self.mcp_config,
                self.env,
                self.agent_config,
                self.wrapper,
                self.setup,
                self.tools,
            ]
        ):
            raise ValueError(
                "at least one integration path or tools list is required"
            )
        return self


# ── Scenario ──────────────────────────────────────────────────────────────────


class Scenario(BaseModel):
    """A benchmark scenario — tasks × modes × models × repetitions.

    A scenario defines the matrix of what to run: which tasks,
    with which modes, on which models, repeated how many times.
    """

    name: str = Field(..., min_length=1, pattern=r"^[a-z][a-z0-9_-]*$")
    description: str = ""
    tasks: list[str] = Field(..., min_length=1)
    modes: list[str] = Field(default_factory=lambda: ["baseline"])
    models: list[str] = Field(default_factory=lambda: ["claude-sonnet-4-6"])
    repetitions: int = Field(default=1, ge=1)
    budget_usd: float = Field(default=1.0, ge=0.0)
    timeout_seconds: int = Field(default=300, ge=1)
    max_workers: int = Field(default=1, ge=1)
    output_dir: str = "results"
