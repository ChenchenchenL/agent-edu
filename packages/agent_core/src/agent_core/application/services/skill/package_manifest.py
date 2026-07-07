from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_core.domain.constants.skill_constants import ALLOWED_SKILL_PACKAGE_TOOLS
from agent_core.domain.entities.skill.package import SKILL_PACKAGE_MANIFEST_REQUIRED_KEYS, SKILL_PACKAGE_SIGNATURE_ALGORITHMS
from agent_core.domain.entities.skill.artifact import SKILL_USAGE_SURFACES
from agent_core.domain.errors import ValidationError


@dataclass(frozen=True)
class NormalizedManifest:
    name: str
    provider: str
    version: str
    surfaces: list[str]
    topic_scope: str
    directives_contract: dict[str, Any]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    tool_permission_profile: dict[str, Any]
    compatibility_range: dict[str, Any]
    allowed_tools: frozenset[str]
    extra: dict[str, Any] = field(default_factory=dict)


class SkillPackageManifestParser:
    def parse(
        self,
        raw_manifest: dict[str, Any],
        *,
        name: str,
        provider: str,
        version: str,
    ) -> NormalizedManifest:
        if not isinstance(raw_manifest, dict):
            raise ValidationError("manifest must be a dict.")
        missing = SKILL_PACKAGE_MANIFEST_REQUIRED_KEYS - set(raw_manifest.keys())
        if missing:
            raise ValidationError(f"manifest missing required keys: {sorted(missing)}")

        surfaces = self._validate_surfaces(raw_manifest["surfaces"])
        topic_scope = self._validate_topic_scope(raw_manifest["topic_scope"])
        directives_contract = self._validate_dict_field(raw_manifest, "directives_contract")
        input_schema = self._validate_dict_field(raw_manifest, "input_schema")
        output_schema = self._validate_dict_field(raw_manifest, "output_schema")
        tool_permission_profile = self._validate_tool_profile(raw_manifest["tool_permission_profile"])
        compatibility_range = self._validate_dict_field(raw_manifest, "compatibility_range")

        allowed_tools = frozenset(tool_permission_profile.get("allowed_tools") or [])
        disallowed = allowed_tools - ALLOWED_SKILL_PACKAGE_TOOLS
        if disallowed:
            raise ValidationError(
                f"tool_permission_profile contains tools outside allowed set: {sorted(disallowed)}"
            )

        known_keys = set(SKILL_PACKAGE_MANIFEST_REQUIRED_KEYS)
        extra = {k: v for k, v in raw_manifest.items() if k not in known_keys}

        return NormalizedManifest(
            name=name,
            provider=provider,
            version=version,
            surfaces=surfaces,
            topic_scope=topic_scope,
            directives_contract=directives_contract,
            input_schema=input_schema,
            output_schema=output_schema,
            tool_permission_profile=tool_permission_profile,
            compatibility_range=compatibility_range,
            allowed_tools=allowed_tools,
            extra=extra,
        )

    @staticmethod
    def _validate_surfaces(value: Any) -> list[str]:
        if not isinstance(value, list) or not value:
            raise ValidationError("manifest.surfaces must be a non-empty list.")
        result: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValidationError("manifest.surfaces must contain non-empty strings.")
            if item not in SKILL_USAGE_SURFACES:
                raise ValidationError(f"manifest.surfaces contains unsupported surface: {item}")
            result.append(item)
        return sorted(set(result))

    @staticmethod
    def _validate_topic_scope(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("manifest.topic_scope must be a non-empty string.")
        return value.strip()

    @staticmethod
    def _validate_dict_field(manifest: dict[str, Any], key: str) -> dict[str, Any]:
        value = manifest.get(key)
        if not isinstance(value, dict):
            raise ValidationError(f"manifest.{key} must be a dict.")
        return dict(value)

    @staticmethod
    def _validate_tool_profile(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValidationError("manifest.tool_permission_profile must be a dict.")
        profile = dict(value)
        allowed_tools = profile.get("allowed_tools")
        if allowed_tools is not None:
            if not isinstance(allowed_tools, list):
                raise ValidationError("manifest.tool_permission_profile.allowed_tools must be a list.")
            for tool in allowed_tools:
                if not isinstance(tool, str) or not tool.strip():
                    raise ValidationError("manifest.tool_permission_profile.allowed_tools must contain non-empty strings.")
        else:
            profile["allowed_tools"] = []
        return profile
