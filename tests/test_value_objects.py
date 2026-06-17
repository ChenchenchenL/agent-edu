"""测试验证值对象."""
import pytest

from agent_core.domain.errors import ValidationError
from agent_core.domain.value_objects.validation import NonEmptyString, require_non_empty
from agent_core.domain.value_objects.identifiers import OperatorId, ArtifactId


def test_require_non_empty_valid():
    """测试非空验证 - 有效输入."""
    result = require_non_empty("valid_value", "field_name")
    assert result == "valid_value"

    # 测试自动trim
    result = require_non_empty("  trimmed  ", "field_name")
    assert result == "trimmed"


def test_require_non_empty_invalid():
    """测试非空验证 - 无效输入."""
    with pytest.raises(ValidationError) as exc_info:
        require_non_empty("", "operator_id")
    assert "operator_id is required" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        require_non_empty("   ", "reason_code")
    assert "reason_code is required" in str(exc_info.value)


def test_non_empty_string_value_object():
    """测试NonEmptyString值对象."""
    # 有效创建
    value = NonEmptyString("test_value")
    assert value.value == "test_value"
    assert str(value) == "test_value"

    # 自动trim
    value = NonEmptyString("  spaces  ")
    assert value.value == "spaces"

    # 拒绝空字符串
    with pytest.raises(ValidationError):
        NonEmptyString("")

    with pytest.raises(ValidationError):
        NonEmptyString("   ")


def test_operator_id_value_object():
    """测试OperatorId值对象."""
    op_id = OperatorId("admin@example.com")
    assert op_id.value == "admin@example.com"

    # 测试相等性
    op_id2 = OperatorId("admin@example.com")
    assert op_id == op_id2

    # 测试不可变性
    assert op_id.__hash__() is not None

    # 拒绝空值
    with pytest.raises(ValidationError):
        OperatorId("")


def test_artifact_id_value_object():
    """测试ArtifactId值对象."""
    artifact_id = ArtifactId("skill_123")
    assert artifact_id.value == "skill_123"

    # 测试格式验证
    with pytest.raises(ValidationError):
        ArtifactId("")


def test_operator_id_from_api_key():
    """测试从API密钥生成操作者ID."""
    op_id = OperatorId.from_api_key("secret-api-key-12345")
    assert op_id.value.startswith("operator:")
    assert len(op_id.value) > 10

    # 同样的密钥产生同样的ID
    op_id2 = OperatorId.from_api_key("secret-api-key-12345")
    assert op_id == op_id2


def test_value_objects_immutability():
    """测试值对象不可变性."""
    op_id = OperatorId("test")
    with pytest.raises(AttributeError):
        op_id.value = "modified"

    artifact_id = ArtifactId("test")
    with pytest.raises(AttributeError):
        artifact_id.value = "modified"

    string_val = NonEmptyString("test")
    with pytest.raises(AttributeError):
        string_val.value = "modified"
