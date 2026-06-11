"""标识符相关的值对象."""
from hashlib import sha256

from agent_core.domain.errors import ValidationError


class OperatorId:
    """操作者ID值对象.

    封装操作者标识符，提供验证和格式化。
    使用自定义 __setattr__ 确保不可变性（兼容 Python 3.6）。
    """

    def __init__(self, value: str):
        """初始化操作者ID.

        Args:
            value: 操作者ID字符串

        Raises:
            ValidationError: 如果值为空
        """
        trimmed = value.strip()
        if not trimmed:
            raise ValidationError("operator_id cannot be empty")
        object.__setattr__(self, '_value', trimmed)

    @property
    def value(self) -> str:
        """获取操作者ID值."""
        return self._value

    @staticmethod
    def from_api_key(api_key):
        """从API密钥生成操作者ID.

        Args:
            api_key: API密钥

        Returns:
            OperatorId实例

        Raises:
            ValidationError: 如果api_key为空
        """
        if not api_key.strip():
            raise ValidationError("api_key cannot be empty")

        # 生成hash作为operator_id
        hash_value = sha256(api_key.encode()).hexdigest()[:12]
        return OperatorId(f"operator:{hash_value}")

    def __str__(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"OperatorId({self._value!r})"

    def __eq__(self, other):
        if isinstance(other, OperatorId):
            return self._value == other._value
        return False

    def __hash__(self):
        return hash(self._value)

    def __setattr__(self, name, value):
        """禁止修改属性，确保不可变性."""
        raise AttributeError("OperatorId is immutable")


class ArtifactId:
    """制品ID值对象.

    封装技能制品、记忆等实体的标识符。
    使用自定义 __setattr__ 确保不可变性（兼容 Python 3.6）。
    """

    def __init__(self, value: str):
        """初始化制品ID.

        Args:
            value: 制品ID字符串

        Raises:
            ValidationError: 如果值为空
        """
        trimmed = value.strip()
        if not trimmed:
            raise ValidationError("artifact_id cannot be empty")
        object.__setattr__(self, '_value', trimmed)

    @property
    def value(self) -> str:
        """获取制品ID值."""
        return self._value

    def __str__(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"ArtifactId({self._value!r})"

    def __eq__(self, other):
        if isinstance(other, ArtifactId):
            return self._value == other._value
        return False

    def __hash__(self):
        return hash(self._value)

    def __setattr__(self, name, value):
        """禁止修改属性，确保不可变性."""
        raise AttributeError("ArtifactId is immutable")
