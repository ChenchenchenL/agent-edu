"""验证相关的值对象和工具函数."""
from agent_core.domain.errors import ValidationError


def require_non_empty(value: str, field_name: str) -> str:
    """验证字符串非空并返回trim后的值.

    Args:
        value: 待验证的字符串
        field_name: 字段名称（用于错误消息）

    Returns:
        Trim后的字符串值

    Raises:
        ValidationError: 如果字符串为空或只包含空白
    """
    trimmed = value.strip()
    if not trimmed:
        raise ValidationError(f"{field_name} is required.")
    return trimmed


class NonEmptyString:
    """非空字符串值对象.

    确保字符串值非空，自动trim空白字符。
    使用自定义 __setattr__ 确保不可变性（兼容 Python 3.6）。
    """

    def __init__(self, value: str):
        """初始化非空字符串.

        Args:
            value: 字符串值

        Raises:
            ValidationError: 如果值为空
        """
        trimmed = value.strip()
        if not trimmed:
            raise ValidationError("Value cannot be empty.")
        object.__setattr__(self, '_value', trimmed)

    @property
    def value(self) -> str:
        """获取字符串值."""
        return self._value

    def __str__(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"NonEmptyString({self._value!r})"

    def __eq__(self, other):
        if isinstance(other, NonEmptyString):
            return self._value == other._value
        return False

    def __hash__(self):
        return hash(self._value)

    def __setattr__(self, name, value):
        """禁止修改属性，确保不可变性."""
        raise AttributeError("NonEmptyString is immutable")
