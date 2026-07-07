"""Phase 5 tests: policy-driven template system.

Tests cover:
1. ToolCapability output schema constrains referenceable fields.
2. SurfacePolicy rejects disallowed capabilities, step counts, variables.
3. PlanTemplate selector only selects from candidates.
4. Legacy tool_plan bridges to single template.
5. Sandbox and runtime use same validation rules.
6. Illegal variables/references/sequences are rejected.
7. Low-privilege surfaces can't use privileged capabilities.
8. Runtime explain shows template info.
9. No arbitrary capabilities can be opened.
10. Models can't freely generate execution plans.
"""

from __future__ import annotations

import pytest

from agent_core.application.services.plan_templates import (
    PlanTemplate,
    PlanTemplateOutputReferenceContract,
    PlanTemplateStep,
    PlanTemplateVariableContract,
    build_plan_template_from_legacy_tool_plan,
)
from agent_core.application.services.plan_template_selector import (
    PlanTemplateSelectionRequest,
    PlanTemplateSelector,
)
from agent_core.application.services.plan_template_validation import (
    PlanTemplateValidator,
)
from agent_core.application.services.surface_policies import (
    SurfacePolicy,
    get_surface_policy,
    require_surface_policy,
)
from agent_core.application.services.tool_capabilities import (
    PARTIAL_REPLAN_CAPABILITY,
    REVIEW_SCHEDULING_CAPABILITY,
    ToolCapability,
    get_capability,
    get_capability_by_tool_name,
)
from agent_core.domain.entities.skill.artifact import SkillArtifact
from agent_core.domain.errors import ValidationError


# ---------------------------------------------------------------------------
# ToolCapability tests
# ---------------------------------------------------------------------------


class TestToolCapability:
    def test_builtin_capabilities_registered(self):
        assert get_capability("review_scheduling") is REVIEW_SCHEDULING_CAPABILITY
        assert get_capability("partial_replan") is PARTIAL_REPLAN_CAPABILITY

    def test_get_capability_by_tool_name(self):
        cap = get_capability_by_tool_name("review_scheduling")
        assert cap is not None
        assert cap.capability_id == "review_scheduling"
        assert cap.tool_name == "review_scheduling"

    def test_unknown_capability_returns_none(self):
        assert get_capability("nonexistent") is None
        assert get_capability_by_tool_name("nonexistent") is None

    def test_partial_replan_allows_output_reference(self):
        assert PARTIAL_REPLAN_CAPABILITY.allows_output_reference("created_task_ids", 0) is True

    def test_partial_replan_rejects_unknown_reference(self):
        assert PARTIAL_REPLAN_CAPABILITY.allows_output_reference("unknown_field", 0) is False
        assert PARTIAL_REPLAN_CAPABILITY.allows_output_reference("created_task_ids", 1) is False

    def test_review_scheduling_has_no_output_references(self):
        assert REVIEW_SCHEDULING_CAPABILITY.allows_output_reference("created_task_ids", 0) is False

    def test_capability_has_required_fields(self):
        cap = REVIEW_SCHEDULING_CAPABILITY
        assert cap.audit_category == "internal_tool"
        assert cap.privilege_profile == "standard"
        assert cap.supports_dry_run is True
        assert "source_task_id" in cap.input_schema.get("properties", {})

    def test_no_arbitrary_capability_can_be_opened(self):
        assert get_capability("arbitrary_http_tool") is None
        assert get_capability("external_api_call") is None


# ---------------------------------------------------------------------------
# SurfacePolicy tests
# ---------------------------------------------------------------------------


class TestSurfacePolicy:
    def test_review_scheduling_policy(self):
        policy = get_surface_policy("review_scheduling")
        assert policy is not None
        assert policy.allows_capability("review_scheduling") is True
        assert policy.allows_capability("partial_replan") is False
        assert policy.allows_step_count(1) is True
        assert policy.allows_step_count(2) is False
        assert policy.allows_variable("$source_task_id") is True
        assert policy.allows_variable("$learner_goal_id") is False

    def test_replan_policy(self):
        policy = get_surface_policy("replan")
        assert policy is not None
        assert policy.allows_capability("partial_replan") is True
        assert policy.allows_capability("review_scheduling") is True
        assert policy.allows_capability("assessment_generation") is False
        assert policy.allows_step_count(2) is True
        assert policy.allows_step_count(3) is False
        assert policy.allows_prior_step_output_reads is True

    def test_chat_policy_has_no_capabilities(self):
        policy = get_surface_policy("chat")
        assert policy is not None
        assert len(policy.allowed_capability_ids) == 0
        assert policy.max_step_count == 0

    def test_unknown_surface_returns_none(self):
        assert get_surface_policy("nonexistent") is None

    def test_require_surface_policy_raises_for_unknown(self):
        with pytest.raises(ValidationError):
            require_surface_policy("nonexistent")

    def test_policy_rejects_disallowed_sequence(self):
        policy = get_surface_policy("review_scheduling")
        assert policy.allows_sequence(("review_scheduling",)) is True
        assert policy.allows_sequence(("partial_replan",)) is False
        assert policy.allows_sequence(("review_scheduling", "partial_replan")) is False

    def test_assessment_generation_policy(self):
        policy = get_surface_policy("assessment_generation")
        assert policy.allows_capability("assessment_generation") is True
        assert policy.allows_variable("$learner_goal_id") is True
        assert policy.allows_variable("$topic_focus") is True
        assert policy.allows_variable("$source_task_id") is False


# ---------------------------------------------------------------------------
# PlanTemplate tests
# ---------------------------------------------------------------------------


class TestPlanTemplate:
    def test_build_from_legacy_tool_plan(self):
        tool_plan = [
            {"step_id": "step_1", "tool_name": "review_scheduling", "payload_template": {"source_task_id": "$source_task_id"}},
        ]
        template = build_plan_template_from_legacy_tool_plan(
            template_id="test_tpl",
            surface="review_scheduling",
            tool_plan=tool_plan,
            source_artifact_id="art-123",
        )
        assert template.template_id == "test_tpl"
        assert template.surface == "review_scheduling"
        assert template.capability_sequence == ("review_scheduling",)
        assert len(template.steps) == 1
        assert template.steps[0].capability_id == "review_scheduling"
        assert template.source_artifact_id == "art-123"

    def test_build_from_legacy_multi_step(self):
        tool_plan = [
            {"step_id": "s1", "tool_name": "partial_replan", "payload_template": {"source_task_id": "$source_task_id"}},
            {"step_id": "s2", "tool_name": "review_scheduling", "payload_template": {"source_task_id": "$steps.s1.created_task_ids[0]"}},
        ]
        template = build_plan_template_from_legacy_tool_plan(
            template_id="replan_tpl",
            surface="replan",
            tool_plan=tool_plan,
        )
        assert template.capability_sequence == ("partial_replan", "review_scheduling")
        assert len(template.steps) == 2
        assert "$source_task_id" in template.variable_contract.required_variables
        assert ("s1", "created_task_ids", 0) in template.output_reference_contract.allowed_references

    def test_to_legacy_tool_plan(self):
        step = PlanTemplateStep(step_id="s1", capability_id="review_scheduling", payload_template={"source_task_id": "$source_task_id"})
        template = PlanTemplate(
            template_id="t1",
            surface="review_scheduling",
            capability_sequence=("review_scheduling",),
            steps=(step,),
            variable_contract=PlanTemplateVariableContract(required_variables=frozenset(), optional_variables=frozenset()),
            output_reference_contract=PlanTemplateOutputReferenceContract(allowed_references=frozenset()),
        )
        legacy = template.to_legacy_tool_plan()
        assert len(legacy) == 1
        assert legacy[0]["step_id"] == "s1"
        assert legacy[0]["tool_name"] == "review_scheduling"

    def test_parse_step_reference(self):
        ref = PlanTemplate.parse_step_reference("$steps.s1.created_task_ids[0]")
        assert ref == ("s1", "created_task_ids", 0)

        ref_none = PlanTemplate.parse_step_reference("$learner_goal_id")
        assert ref_none is None

        ref_no_index = PlanTemplate.parse_step_reference("$steps.s1.result")
        assert ref_no_index == ("s1", "result", None)


# ---------------------------------------------------------------------------
# PlanTemplateValidator tests
# ---------------------------------------------------------------------------


class TestPlanTemplateValidator:
    def setup_method(self):
        self.validator = PlanTemplateValidator()

    def _make_template(self, surface, steps_data):
        steps = []
        cap_ids = []
        for s in steps_data:
            steps.append(PlanTemplateStep(
                step_id=s["step_id"],
                capability_id=s["capability_id"],
                payload_template=s.get("payload_template", {}),
            ))
            cap_ids.append(s["capability_id"])
        return PlanTemplate(
            template_id="test",
            surface=surface,
            capability_sequence=tuple(cap_ids),
            steps=tuple(steps),
            variable_contract=PlanTemplateVariableContract(required_variables=frozenset(), optional_variables=frozenset()),
            output_reference_contract=PlanTemplateOutputReferenceContract(allowed_references=frozenset()),
        )

    def test_valid_single_step_template(self):
        template = self._make_template("review_scheduling", [
            {"step_id": "s1", "capability_id": "review_scheduling", "payload_template": {"source_task_id": "$source_task_id"}},
        ])
        result = self.validator.validate_template(template=template, surface="review_scheduling")
        assert result.valid is True
        assert result.validated_template is not None

    def test_rejects_unknown_capability(self):
        template = self._make_template("review_scheduling", [
            {"step_id": "s1", "capability_id": "nonexistent_tool"},
        ])
        result = self.validator.validate_template(template=template, surface="review_scheduling")
        assert result.valid is False
        assert any("unknown_capability" in r for r in result.rejection_reason_codes)

    def test_rejects_capability_not_allowed_on_surface(self):
        template = self._make_template("review_scheduling", [
            {"step_id": "s1", "capability_id": "partial_replan"},
        ])
        result = self.validator.validate_template(template=template, surface="review_scheduling")
        assert result.valid is False
        assert any("capability_not_allowed" in r for r in result.rejection_reason_codes)

    def test_rejects_step_count_exceeds_policy(self):
        template = self._make_template("review_scheduling", [
            {"step_id": "s1", "capability_id": "review_scheduling"},
            {"step_id": "s2", "capability_id": "review_scheduling"},
        ])
        result = self.validator.validate_template(template=template, surface="review_scheduling")
        assert result.valid is False
        assert "step_count_exceeds_policy" in result.rejection_reason_codes

    def test_rejects_unsupported_sequence(self):
        template = self._make_template("review_scheduling", [
            {"step_id": "s1", "capability_id": "review_scheduling"},
        ])
        template_reversed = PlanTemplate(
            template_id="test",
            surface="review_scheduling",
            capability_sequence=("partial_replan",),
            steps=(PlanTemplateStep(step_id="s1", capability_id="partial_replan", payload_template={}),),
            variable_contract=PlanTemplateVariableContract(required_variables=frozenset(), optional_variables=frozenset()),
            output_reference_contract=PlanTemplateOutputReferenceContract(allowed_references=frozenset()),
        )
        result = self.validator.validate_template(template=template_reversed, surface="review_scheduling")
        assert result.valid is False
        assert "unsupported_capability_sequence" in result.rejection_reason_codes

    def test_rejects_unsupported_variable(self):
        template = self._make_template("review_scheduling", [
            {"step_id": "s1", "capability_id": "review_scheduling", "payload_template": {"goal": "$learner_goal_id"}},
        ])
        result = self.validator.validate_template(template=template, surface="review_scheduling")
        assert result.valid is False
        assert any("unsupported_variable" in r for r in result.rejection_reason_codes)

    def test_rejects_prior_step_output_reads_when_not_allowed(self):
        template = self._make_template("review_scheduling", [
            {"step_id": "s1", "capability_id": "review_scheduling", "payload_template": {"source_task_id": "$source_task_id"}},
        ])
        template_with_ref = PlanTemplate(
            template_id="test",
            surface="review_scheduling",
            capability_sequence=("review_scheduling",),
            steps=(PlanTemplateStep(
                step_id="s1",
                capability_id="review_scheduling",
                payload_template={"ref": "$steps.s1.created_task_ids[0]"},
            ),),
            variable_contract=PlanTemplateVariableContract(required_variables=frozenset(), optional_variables=frozenset()),
            output_reference_contract=PlanTemplateOutputReferenceContract(allowed_references=frozenset()),
        )
        result = self.validator.validate_template(template=template_with_ref, surface="review_scheduling")
        assert result.valid is False
        assert "prior_step_output_reads_not_allowed" in result.rejection_reason_codes

    def test_valid_replan_multi_step(self):
        template = self._make_template("replan", [
            {"step_id": "s1", "capability_id": "partial_replan", "payload_template": {"source_task_id": "$source_task_id"}},
            {"step_id": "s2", "capability_id": "review_scheduling", "payload_template": {"source_task_id": "$steps.s1.created_task_ids[0]"}},
        ])
        result = self.validator.validate_template(template=template, surface="replan")
        assert result.valid is True

    def test_rejects_unknown_surface(self):
        template = self._make_template("nonexistent", [
            {"step_id": "s1", "capability_id": "review_scheduling"},
        ])
        result = self.validator.validate_template(template=template, surface="nonexistent")
        assert result.valid is False
        assert "unknown_surface" in result.rejection_reason_codes

    def test_rejects_duplicate_step_id(self):
        template = self._make_template("replan", [
            {"step_id": "s1", "capability_id": "partial_replan", "payload_template": {"source_task_id": "$source_task_id"}},
            {"step_id": "s1", "capability_id": "review_scheduling", "payload_template": {"source_task_id": "$source_task_id"}},
        ])
        result = self.validator.validate_template(template=template, surface="replan")
        assert result.valid is False
        assert any("duplicate_step_id" in r for r in result.rejection_reason_codes)

    def test_rejects_disallowed_output_reference(self):
        template = PlanTemplate(
            template_id="test",
            surface="replan",
            capability_sequence=("partial_replan", "review_scheduling"),
            steps=(
                PlanTemplateStep(step_id="s1", capability_id="partial_replan", payload_template={"source_task_id": "$source_task_id"}),
                PlanTemplateStep(step_id="s2", capability_id="review_scheduling", payload_template={"source_task_id": "$steps.s1.unknown_field[0]"}),
            ),
            variable_contract=PlanTemplateVariableContract(required_variables=frozenset(), optional_variables=frozenset()),
            output_reference_contract=PlanTemplateOutputReferenceContract(allowed_references=frozenset()),
        )
        result = self.validator.validate_template(template=template, surface="replan")
        assert result.valid is False
        assert any("disallowed_output_reference" in r for r in result.rejection_reason_codes)

    def test_empty_template_rejected(self):
        template = PlanTemplate(
            template_id="test",
            surface="review_scheduling",
            capability_sequence=(),
            steps=(),
            variable_contract=PlanTemplateVariableContract(required_variables=frozenset(), optional_variables=frozenset()),
            output_reference_contract=PlanTemplateOutputReferenceContract(allowed_references=frozenset()),
        )
        result = self.validator.validate_template(template=template, surface="review_scheduling")
        assert result.valid is False
        assert "empty_template" in result.rejection_reason_codes


# ---------------------------------------------------------------------------
# PlanTemplateSelector tests
# ---------------------------------------------------------------------------


class TestPlanTemplateSelector:
    def setup_method(self):
        self.selector = PlanTemplateSelector()

    def _make_template(self, template_id, surface, cap_sequence, steps_data):
        steps = tuple(
            PlanTemplateStep(step_id=s["step_id"], capability_id=s["capability_id"], payload_template=s.get("payload_template", {}))
            for s in steps_data
        )
        return PlanTemplate(
            template_id=template_id,
            surface=surface,
            capability_sequence=cap_sequence,
            steps=steps,
            variable_contract=PlanTemplateVariableContract(required_variables=frozenset(), optional_variables=frozenset()),
            output_reference_contract=PlanTemplateOutputReferenceContract(allowed_references=frozenset()),
        )

    def test_selects_valid_template(self):
        tpl = self._make_template("t1", "review_scheduling", ("review_scheduling",), [
            {"step_id": "s1", "capability_id": "review_scheduling", "payload_template": {"source_task_id": "$source_task_id"}},
        ])
        result = self.selector.select_template(PlanTemplateSelectionRequest(
            surface="review_scheduling",
            candidate_templates=[tpl],
            runtime_variables={"$source_task_id": "task-123"},
        ))
        assert result.selected_template is not None
        assert result.selected_template.template_id == "t1"
        assert result.policy_validated is True

    def test_rejects_invalid_template(self):
        tpl = self._make_template("t1", "review_scheduling", ("partial_replan",), [
            {"step_id": "s1", "capability_id": "partial_replan"},
        ])
        result = self.selector.select_template(PlanTemplateSelectionRequest(
            surface="review_scheduling",
            candidate_templates=[tpl],
            runtime_variables={},
        ))
        assert result.selected_template is None
        assert result.policy_validated is False
        assert len(result.rejected_templates) == 1

    def test_does_not_invent_new_plan(self):
        result = self.selector.select_template(PlanTemplateSelectionRequest(
            surface="review_scheduling",
            candidate_templates=[],
            runtime_variables={},
        ))
        assert result.selected_template is None
        assert result.expanded_tool_plan == []
        assert result.capability_sequence == ()

    def test_build_candidates_from_legacy_tool_plan(self):
        tool_plan = [
            {"step_id": "s1", "tool_name": "review_scheduling", "payload_template": {"source_task_id": "$source_task_id"}},
        ]
        candidates = self.selector.build_candidates_from_legacy_tool_plan(
            surface="review_scheduling",
            tool_plan=tool_plan,
            source_artifact_id="art-1",
        )
        assert len(candidates) == 1
        assert candidates[0].capability_sequence == ("review_scheduling",)
        assert candidates[0].source_artifact_id == "art-1"

    def test_build_candidates_from_empty_tool_plan(self):
        candidates = self.selector.build_candidates_from_legacy_tool_plan(
            surface="review_scheduling",
            tool_plan=[],
        )
        assert candidates == []

    def test_selects_first_valid_when_multiple_candidates(self):
        valid = self._make_template("valid", "review_scheduling", ("review_scheduling",), [
            {"step_id": "s1", "capability_id": "review_scheduling", "payload_template": {"source_task_id": "$source_task_id"}},
        ])
        invalid = self._make_template("invalid", "review_scheduling", ("partial_replan",), [
            {"step_id": "s1", "capability_id": "partial_replan"},
        ])
        result = self.selector.select_template(PlanTemplateSelectionRequest(
            surface="review_scheduling",
            candidate_templates=[invalid, valid],
            runtime_variables={"$source_task_id": "task-1"},
        ))
        assert result.selected_template is not None
        assert result.selected_template.template_id == "valid"
        assert len(result.rejected_templates) == 1


# ---------------------------------------------------------------------------
# Artifact backward compat bridge tests
# ---------------------------------------------------------------------------


class TestArtifactPlanTemplateBridge:
    def test_legacy_tool_plan_bridges_to_plan_templates(self):
        artifact = SkillArtifact.build(
            name="test_skill",
            version="0.1.1",
            skill_type="learned",
            scope="review_scheduling",
            status="candidate",
            description="test",
            tool_plan=[
                {"step_id": "s1", "tool_name": "review_scheduling", "payload_template": {"source_task_id": "$source_task_id"}},
            ],
        )
        assert len(artifact.plan_templates) == 1
        assert artifact.plan_templates[0]["surface"] == "review_scheduling"
        assert len(artifact.plan_templates[0]["steps"]) == 1

    def test_explicit_plan_templates_preferred(self):
        artifact = SkillArtifact.build(
            name="test_skill",
            version="0.1.1",
            skill_type="learned",
            scope="review_scheduling",
            status="candidate",
            description="test",
            tool_plan=[],
            plan_templates=[
                {"template_id": "explicit_tpl", "surface": "review_scheduling", "steps": []},
            ],
        )
        assert len(artifact.plan_templates) == 1
        assert artifact.plan_templates[0]["template_id"] == "explicit_tpl"

    def test_get_plan_template_candidates_from_tool_plan(self):
        artifact = SkillArtifact.build(
            name="test_skill",
            version="0.1.1",
            skill_type="learned",
            scope="review_scheduling",
            status="candidate",
            description="test",
            tool_plan=[
                {"step_id": "s1", "tool_name": "review_scheduling", "payload_template": {}},
            ],
        )
        candidates = artifact.get_plan_template_candidates()
        assert len(candidates) == 1
        assert candidates[0]["surface"] == "review_scheduling"

    def test_get_plan_template_candidates_from_plan_templates(self):
        artifact = SkillArtifact.build(
            name="test_skill",
            version="0.1.1",
            skill_type="learned",
            scope="review_scheduling",
            status="candidate",
            description="test",
            plan_templates=[
                {"template_id": "tpl1", "surface": "review_scheduling", "steps": []},
            ],
        )
        candidates = artifact.get_plan_template_candidates()
        assert len(candidates) == 1
        assert candidates[0]["template_id"] == "tpl1"

    def test_empty_artifact_has_no_candidates(self):
        artifact = SkillArtifact.build(
            name="test_skill",
            version="0.1.1",
            skill_type="baseline",
            scope="chat",
            status="candidate",
            description="test",
        )
        candidates = artifact.get_plan_template_candidates()
        assert candidates == []


# ---------------------------------------------------------------------------
# Sandbox and runtime use same validation rules
# ---------------------------------------------------------------------------


class TestSharedValidationRules:
    def test_sandbox_and_runtime_share_validator(self):
        validator = PlanTemplateValidator()
        selector = PlanTemplateSelector()
        tool_plan = [
            {"step_id": "s1", "tool_name": "review_scheduling", "payload_template": {"source_task_id": "$source_task_id"}},
        ]
        candidates = selector.build_candidates_from_legacy_tool_plan(
            surface="review_scheduling",
            tool_plan=tool_plan,
        )
        for candidate in candidates:
            result = validator.validate_template(template=candidate, surface="review_scheduling")
            assert result.valid is True

    def test_invalid_plan_rejected_by_same_validator(self):
        validator = PlanTemplateValidator()
        selector = PlanTemplateSelector()
        tool_plan = [
            {"step_id": "s1", "tool_name": "arbitrary_tool", "payload_template": {}},
        ]
        candidates = selector.build_candidates_from_legacy_tool_plan(
            surface="review_scheduling",
            tool_plan=tool_plan,
        )
        for candidate in candidates:
            result = validator.validate_template(template=candidate, surface="review_scheduling")
            assert result.valid is False


# ---------------------------------------------------------------------------
# Runtime explain template info
# ---------------------------------------------------------------------------


class TestRuntimeExplainTemplateInfo:
    def test_capability_selection_has_template_id_field(self):
        from agent_core.application.services.skill.capability import CapabilitySelection
        selection = CapabilitySelection(
            requested_capability="chat.respond",
            selected_artifact_id="art-1",
            selected_capability="explain_concept",
            tool_plan_template_id="tpl-123",
        )
        assert selection.tool_plan_template_id == "tpl-123"

    def test_capability_selection_default_template_id_is_none(self):
        from agent_core.application.services.skill.capability import CapabilitySelection
        selection = CapabilitySelection(
            requested_capability="chat.respond",
            selected_artifact_id=None,
            selected_capability="explain_concept",
        )
        assert selection.tool_plan_template_id is None


# ---------------------------------------------------------------------------
# Model cannot freely generate plans
# ---------------------------------------------------------------------------


class TestNoFreePlanGeneration:
    def test_selector_cannot_invent_plans(self):
        selector = PlanTemplateSelector()
        result = selector.select_template(PlanTemplateSelectionRequest(
            surface="replan",
            candidate_templates=[],
            runtime_variables={},
        ))
        assert result.selected_template is None
        assert result.expanded_tool_plan == []

    def test_validator_rejects_unknown_capabilities(self):
        validator = PlanTemplateValidator()
        template = PlanTemplate(
            template_id="rogue",
            surface="replan",
            capability_sequence=("arbitrary_http_tool",),
            steps=(PlanTemplateStep(step_id="s1", capability_id="arbitrary_http_tool", payload_template={}),),
            variable_contract=PlanTemplateVariableContract(required_variables=frozenset(), optional_variables=frozenset()),
            output_reference_contract=PlanTemplateOutputReferenceContract(allowed_references=frozenset()),
        )
        result = validator.validate_template(template=template, surface="replan")
        assert result.valid is False

    def test_low_privilege_surface_cannot_use_unauthorized_capability(self):
        validator = PlanTemplateValidator()
        template = PlanTemplate(
            template_id="rogue",
            surface="chat",
            capability_sequence=("review_scheduling",),
            steps=(PlanTemplateStep(step_id="s1", capability_id="review_scheduling", payload_template={}),),
            variable_contract=PlanTemplateVariableContract(required_variables=frozenset(), optional_variables=frozenset()),
            output_reference_contract=PlanTemplateOutputReferenceContract(allowed_references=frozenset()),
        )
        result = validator.validate_template(template=template, surface="chat")
        assert result.valid is False
