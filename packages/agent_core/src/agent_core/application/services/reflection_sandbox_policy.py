"""Sandbox profile definitions and admission policy.

Defines the sandbox profiles that control what a proposal is allowed
to do inside the sandbox.  Each profile declares:

- allowed tool names
- whether tool plan preview is permitted
- sample count cap
- whether live LLM replay is allowed
- whether external side-effect simulation is allowed
- audit level

Profiles are selected by the admission service based on proposal
risk level and governance context.
"""

from __future__ import annotations

from dataclasses import dataclass, field


SANDBOX_PROFILES = {
    "baseline": "baseline_profile",
    "restricted_high_risk": "restricted_high_risk_profile",
    "privileged_review": "privileged_review_profile",
}


@dataclass(frozen=True)
class SandboxProfile:
    """Defines resource and capability limits for a sandbox run."""

    name: str
    allowed_tools: frozenset[str]
    allow_tool_plan_preview: bool
    sample_count_cap: int
    allow_live_llm_replay: bool
    allow_external_side_effect_simulation: bool
    audit_level: str

    def to_summary(self) -> dict[str, object]:
        return {
            "profile": self.name,
            "allowed_tools": sorted(self.allowed_tools),
            "allow_tool_plan_preview": self.allow_tool_plan_preview,
            "sample_count_cap": self.sample_count_cap,
            "allow_live_llm_replay": self.allow_live_llm_replay,
            "allow_external_side_effect_simulation": self.allow_external_side_effect_simulation,
            "audit_level": self.audit_level,
        }


BASELINE_PROFILE = SandboxProfile(
    name="baseline_profile",
    allowed_tools=frozenset({
        "Read", "Write", "Edit", "Bash",
        "WebFetch", "WebSearch", "Agent", "AskUserQuestion",
    }),
    allow_tool_plan_preview=True,
    sample_count_cap=5,
    allow_live_llm_replay=True,
    allow_external_side_effect_simulation=False,
    audit_level="standard",
)

RESTRICTED_HIGH_RISK_PROFILE = SandboxProfile(
    name="restricted_high_risk_profile",
    allowed_tools=frozenset({"Read", "WebFetch"}),
    allow_tool_plan_preview=True,
    sample_count_cap=3,
    allow_live_llm_replay=False,
    allow_external_side_effect_simulation=False,
    audit_level="elevated",
)

PRIVILEGED_REVIEW_PROFILE = SandboxProfile(
    name="privileged_review_profile",
    allowed_tools=frozenset({"Read"}),
    allow_tool_plan_preview=False,
    sample_count_cap=2,
    allow_live_llm_replay=False,
    allow_external_side_effect_simulation=False,
    audit_level="maximum",
)

STRICTER_HIGH_RISK_PROFILE = SandboxProfile(
    name="stricter_high_risk_profile",
    allowed_tools=frozenset({"Read"}),
    allow_tool_plan_preview=False,
    sample_count_cap=2,
    allow_live_llm_replay=False,
    allow_external_side_effect_simulation=False,
    audit_level="maximum",
)

ALL_PROFILES: dict[str, SandboxProfile] = {
    "baseline_profile": BASELINE_PROFILE,
    "restricted_high_risk_profile": RESTRICTED_HIGH_RISK_PROFILE,
    "privileged_review_profile": PRIVILEGED_REVIEW_PROFILE,
    "stricter_high_risk_profile": STRICTER_HIGH_RISK_PROFILE,
}


def get_profile(name: str) -> SandboxProfile:
    profile = ALL_PROFILES.get(name)
    if profile is None:
        raise ValueError(f"Unknown sandbox profile: {name}")
    return profile


def profile_for_risk_level(risk_level: str) -> SandboxProfile:
    if risk_level == "high":
        return STRICTER_HIGH_RISK_PROFILE
    return BASELINE_PROFILE
