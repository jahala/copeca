"""Domain model dataclasses for copeca — Pydantic v2, pure data, no I/O.

Architecture invariant (§7): this file must never import from runners/,
repos/, results/, or orchestration/. It is mechanically enforceable in CI.
"""

from enum import Enum
from typing import Any

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


class Category(str, Enum):
    """Capability axis — orthogonal to TaskType's grading axis.

    locate — report one self-contained, named thing.
    trace  — map a relationship spanning files (callers, implementors, control-flow).
    fix    — change code until a stated test passes.
    debug  — diagnose a defect via git history, then resolve or explain it.
    reason — comprehend given code with no navigation (a self-contained snippet).
    """

    locate = "locate"
    trace = "trace"
    fix = "fix"
    debug = "debug"
    reason = "reason"


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
    def find_required_for_search_actions(cls, v: str, info: "ValidationInfo") -> str:
        action = info.data.get("action", MutationAction.replace)
        if action in (MutationAction.replace, MutationAction.delete, MutationAction.insert_after):
            if not v:
                raise ValueError(f"find is required for action '{action.value}'")
        return v

    @field_validator("content")
    @classmethod
    def content_required_for_create_and_insert(cls, v: str, info: "ValidationInfo") -> str:
        action = info.data.get("action", MutationAction.replace)
        if action in (MutationAction.create, MutationAction.insert_after):
            if not v:
                raise ValueError(f"content is required for action '{action.value}'")
        return v


class MutationStep(BaseModel):
    """One commit step in a mutation_sequence — mutations applied then committed.

    Used for debug tasks: each step builds real git history so the agent can
    use git log / git diff to discover and diagnose the regression.
    """

    message: str = Field(..., min_length=1)
    mutations: list[Mutation] = Field(..., min_length=1)


# ── Task ──────────────────────────────────────────────────────────────────────


class Task(BaseModel):
    """A benchmark task — data, never code (design decision #15)."""

    name: str = Field(..., min_length=1, pattern=r"^[a-z][a-z0-9_-]*$")
    description: str = ""
    source: str = Field(..., min_length=1)
    repo: str = Field(..., min_length=1)
    # Optional per-task commit override: pins this task's worktree at a specific
    # code state, overriding the repos.yaml default so one repo can serve tasks
    # authored against different commits (SD-O). None = use the repos.yaml pin.
    commit: str | None = None
    type: TaskType
    category: Category
    language: Language
    difficulty: Difficulty
    version: int = Field(default=1, ge=1)
    prompt: str = Field(..., min_length=1)
    ground_truth: GroundTruth
    mutations: list[Mutation] = Field(default_factory=list)
    # Sequence of committed mutations for debug tasks. Each step applies its
    # mutations to the worktree then `git commit`s them, building real history
    # for the agent to navigate. Applied BEFORE working-tree `mutations`.
    mutation_sequence: list[MutationStep] = Field(default_factory=list)
    # Tool-neutrality control (#52): True marks a non-regression task where a
    # codebase tool should not help (answer-in-context / single-file / pure
    # reasoning). The report measures the tool's delta on these to catch
    # regression or over-specialization. Orthogonal to category.
    control: bool = False

    @model_validator(mode="after")
    def _category_consistent_with_type(self) -> "Task":
        """`type` fixes grading; `category` is the capability lens — they must agree.

        comprehension ⟹ locate/trace/debug; edit ⟹ fix/debug. `debug` spans both:
        explain-a-diff is comprehension+debug, find+fix-a-regression is edit+debug.
        """
        comprehension_ok = {Category.locate, Category.trace, Category.debug, Category.reason}
        edit_ok = {Category.fix, Category.debug}
        if self.type == TaskType.comprehension and self.category not in comprehension_ok:
            raise ValueError(
                f"comprehension task '{self.name}': category '{self.category.value}' "
                "invalid (allowed: locate, trace, debug, reason)"
            )
        if self.type == TaskType.edit and self.category not in edit_ok:
            raise ValueError(
                f"edit task '{self.name}': category '{self.category.value}' "
                "invalid (allowed: fix, debug)"
            )
        return self


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
            raise ValueError("at least one integration path or tools list is required")
        return self


# ── Runner ────────────────────────────────────────────────────────────────────


class IsolationSpec(BaseModel):
    """Per-CLI clean-room descriptor — the data the orchestrator reads to apply
    the isolation contract uniformly, with no per-CLI branches in the engine
    (architecture §13.4, invariant 4).

    All fields are optional with safe defaults so a runner YAML that omits the
    ``isolation:`` block behaves the same as one that declares every field empty.
    """

    # Env var pointing at the per-run private config home
    # (CLAUDE_CONFIG_DIR / CODEX_HOME / GEMINI_CLI_HOME).
    config_home_env: str | None = None
    # Flags forcing "only my MCP": claude --strict-mcp-config,
    # codex --ignore-user-config, gemini --allowed-mcp-server-names.
    strict_mcp_flags: list[str] = Field(default_factory=list)
    # Env vars that neutralize ambient instruction files
    # (e.g. {CLAUDE_CODE_DISABLE_CLAUDE_MDS: "1"}).
    disable_ambient_env: dict[str, str] = Field(default_factory=dict)
    # Flags that disable session persistence
    # (e.g. [--no-session-persistence] / [--ephemeral]).
    disable_session_flags: list[str] = Field(default_factory=list)
    # Env vars that disable telemetry / nonessential traffic
    # (e.g. {CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1"}).
    disable_telemetry_env: dict[str, str] = Field(default_factory=dict)
    # File names to scan for in the pre-run workdir
    # (CLAUDE.md / AGENTS.md / GEMINI.md).
    ambient_files: list[str] = Field(default_factory=list)
    # Preflight asserts this env var is present before the run
    # (ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY).
    requires_api_key_env: str | None = None
    # Command to resolve the CLI/tool version for provenance
    # (e.g. [claude, --version]).
    version_cmd: list[str] = Field(default_factory=list)


class RunnerConfig(BaseModel):
    """A loaded runner config — the CLI interface plus pricing.

    Data, not code: the interface fields (``cli``, ``default_args``, ``arg_map``,
    ``invoke_template``, ``config_dir_env``, ``parser``) come from the runner
    YAML's ``runner:`` block; ``pricing`` comes from its top-level ``pricing``
    key. copeca's build_runner reads this and constructs a SubprocessRunner — no
    agent's flags are hardcoded. ``parser`` is a NAME resolved via the parser
    registry. ``cli`` defaults to the runner file's stem (filled by the loader).
    """

    cli: str = ""  # binary name; loader fills the file stem when left empty
    default_args: list[str] = Field(default_factory=list)
    arg_map: dict[str, str] = Field(default_factory=dict)
    invoke_template: str = ""
    # Fold the system prompt into the positional prompt for CLIs with no
    # system-prompt flag (e.g. codex exec). Default off — claude uses --system-prompt.
    prepend_system_prompt: bool = False
    # When True, MCP is delivered as repeated -c mcp_servers.<name>.command/args
    # overrides instead of a --mcp-config flag. codex has no --mcp-config; it
    # reads MCP config through its -c config-override mechanism.
    mcp_via_config_overrides: bool = False
    config_dir_env: str | None = None
    parser: str = ""
    # Raw pricing as authored: each model -> {input, output, cache_*: float,
    # updated: str}. Kept as-is so the cost model and staleness check (which read
    # it by key name) consume the same shape they always have.
    pricing: dict[str, dict[str, Any]] | None = None
    # Per-CLI clean-room descriptor (architecture §13.4). Safe empty defaults
    # when the runner YAML omits the isolation: block.
    isolation: IsolationSpec = Field(default_factory=IsolationSpec)

    @model_validator(mode="after")
    def arg_map_or_invoke_template(self) -> "RunnerConfig":
        """A runner must declare how to build its command (arg_map or template)."""
        if not self.arg_map and not self.invoke_template:
            raise ValueError("runner interface needs either 'arg_map' or 'invoke_template'")
        return self


# ── AdversarialThresholds ──────────────────────────────────────────────────────


class AdversarialThresholds(BaseModel):
    """Configurable thresholds for adversarial flag computation (§5).

    All fields have defaults matching the plan's documented values.
    Set per-scenario in the YAML to tune detection sensitivity.
    """

    snowball_factor: float = Field(default=2.0, gt=0)
    talkative_tokens: int = Field(default=1000, ge=1)
    tool_storm_calls: int = Field(default=50, ge=1)


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
    adversarial_thresholds: AdversarialThresholds = Field(default_factory=AdversarialThresholds)
