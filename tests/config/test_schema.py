"""Test JSON Schema validation for copeca task YAML files.

Validates that the bundled task.schema.json correctly enforces all
constraints from the copeca domain model.
"""

import json

import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError, validate

from copeca.config.resources import data_path

SCHEMA_PATH = data_path("schemas", "task.schema.json")


@pytest.fixture
def task_schema():
    """Load the JSON Schema from disk."""
    with open(SCHEMA_PATH) as f:
        return json.load(f)


class TestComprehensionTaskSchema:
    """Schema validates comprehension tasks correctly."""

    def test_valid_minimal_comprehension(self, task_schema):
        """A minimal valid comprehension task passes validation."""
        doc = yaml.safe_load("""
name: rg_trait_implementors
description: Find all implementors of the Matcher trait
source: SWE-QA (Apache-2.0)
repo: ripgrep
type: comprehension
category: locate
language: rust
difficulty: hard
version: 1
prompt: |
  Find the Matcher trait definition and list all implementors.
ground_truth:
  required_strings:
    - Matcher
    - find_at
  all_of:
    - RegexMatcher
  forbidden_strings:
    - I cannot
""")
        validate(doc, task_schema)

    def test_missing_name_fails(self, task_schema):
        """YAML missing the required 'name' field fails validation."""
        doc = yaml.safe_load("""
source: SWE-QA (Apache-2.0)
repo: ripgrep
type: comprehension
category: locate
language: rust
difficulty: hard
version: 1
prompt: Find the trait.
ground_truth:
  required_strings:
    - test
""")
        with pytest.raises(ValidationError, match="name"):
            validate(doc, task_schema)

    def test_empty_source_fails(self, task_schema):
        """Source with empty string fails minLength constraint."""
        doc = yaml.safe_load("""
name: rg_test
source: ""
repo: ripgrep
type: comprehension
category: locate
language: rust
difficulty: hard
version: 1
prompt: test
ground_truth:
  required_strings:
    - test
""")
        with pytest.raises(ValidationError, match="source"):
            validate(doc, task_schema)


class TestEditTaskSchema:
    """Schema validates edit tasks correctly."""

    def test_valid_edit_task(self, task_schema):
        """A valid edit task with mutations and test_command passes."""
        doc = yaml.safe_load("""
name: rg_edit_line_count
description: Fix off-by-one in line counting
source: tilth-benchmark (MIT)
repo: ripgrep
type: edit
category: fix
language: rust
difficulty: medium
version: 1
prompt: |
  The count() function is returning one more than the actual number.
mutations:
  - file: crates/searcher/src/lines.rs
    find: "memchr::memchr_iter(line_term, bytes).count() as u64"
    replace: "memchr::memchr_iter(line_term, bytes).count() as u64 + 1"
test_command:
  - cargo
  - test
  - -p
  - grep-searcher
  - line_count
ground_truth:
  required_strings: []
""")
        validate(doc, task_schema)

    def test_edit_task_without_test_command_is_schema_valid(self, task_schema):
        """An edit task without test_command passes schema validation.

        The JSON Schema validates structure (required fields, types, enums).
        Conditional constraints (edit → test_command required) are enforced
        by the Pydantic layer in config/loader.py. The two-layer design is
        deliberate: schema for user-facing errors, Pydantic for type safety.
        """
        doc = yaml.safe_load("""
name: rg_edit_test
source: SWE-QA (Apache-2.0)
repo: ripgrep
type: edit
category: fix
language: rust
difficulty: medium
version: 1
prompt: fix it
ground_truth:
  required_strings: []
""")
        validate(doc, task_schema)  # passes structural validation


class TestCategoryAndControl:
    """Schema accepts the `reason` category and the `control` flag (#52)."""

    def test_reason_category_valid(self, task_schema):
        doc = yaml.safe_load("""
name: rg_reason_in_context
source: tilth-benchmark (MIT)
repo: ripgrep
type: comprehension
category: reason
language: rust
difficulty: easy
version: 1
prompt: What does this self-contained function return for an empty slice?
ground_truth:
  required_strings:
    - None
""")
        validate(doc, task_schema)

    def test_control_flag_valid(self, task_schema):
        doc = yaml.safe_load("""
name: rg_control_reason
source: tilth-benchmark (MIT)
repo: ripgrep
type: comprehension
category: reason
control: true
language: rust
difficulty: easy
version: 1
prompt: What does this self-contained function return?
ground_truth:
  required_strings:
    - None
""")
        validate(doc, task_schema)

    def test_control_must_be_boolean(self, task_schema):
        doc = yaml.safe_load("""
name: rg_control_badtype
source: tilth-benchmark (MIT)
repo: ripgrep
type: comprehension
category: locate
control: "yes"
language: rust
difficulty: easy
version: 1
prompt: test
ground_truth:
  required_strings:
    - x
""")
        with pytest.raises(ValidationError):
            validate(doc, task_schema)


class TestSchemaMetadata:
    """Schema is well-formed and versionable."""

    def test_schema_is_valid_json_schema(self, task_schema):
        """The schema file itself is a valid JSON Schema document."""
        Draft202012Validator.check_schema(task_schema)

    def test_additional_properties_forbidden(self, task_schema):
        """Unknown fields in task YAML are rejected (additionalProperties: false)."""
        doc = yaml.safe_load("""
name: rg_test
source: SWE-QA (Apache-2.0)
repo: ripgrep
type: comprehension
category: locate
language: rust
difficulty: hard
version: 1
prompt: test
unknown_field_xyz: 42
ground_truth:
  required_strings:
    - test
""")
        with pytest.raises(ValidationError):
            validate(doc, task_schema)


class TestScenarioSchema:
    """Schema validates scenario YAML correctly."""

    SCENARIO_SCHEMA_PATH = SCHEMA_PATH.parent / "scenario.schema.json"

    @pytest.fixture
    def scenario_schema(self):
        with open(self.SCENARIO_SCHEMA_PATH) as f:
            return json.load(f)

    def test_valid_scenario_passes_validation(self, scenario_schema):
        """Minimal valid scenario passes jsonschema validation."""
        doc = yaml.safe_load("""
name: test_scenario
tasks: [task_a]
modes: [baseline]
models: [claude-sonnet-4-6]
repetitions: 3
""")
        validate(doc, scenario_schema)

    def test_missing_name_fails_validation(self, scenario_schema):
        doc = yaml.safe_load("""
tasks: [task_a]
modes: [baseline]
repetitions: 1
""")
        with pytest.raises(ValidationError, match="name"):
            validate(doc, scenario_schema)

    def test_empty_tasks_fails_validation(self, scenario_schema):
        doc = yaml.safe_load("""
name: test
tasks: []
modes: [baseline]
repetitions: 1
""")
        with pytest.raises(ValidationError):
            validate(doc, scenario_schema)

    def test_scenario_schema_is_valid_json_schema(self, scenario_schema):
        Draft202012Validator.check_schema(scenario_schema)
