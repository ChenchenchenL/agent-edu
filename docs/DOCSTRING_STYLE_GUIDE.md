# Docstring Style Guide

## 统一使用 Google Style

所有Python代码必须使用Google Style docstring。

## 模块级文档

```python
"""模块的简短描述.

可选的详细说明，解释模块的目的和用法。
"""
```

## 函数/方法文档

```python
def function_name(param1: str, param2: int) -> bool:
    """简短的一行描述.

    可选的详细说明。可以有多个段落。

    Args:
        param1: 参数1的描述
        param2: 参数2的描述

    Returns:
        返回值的描述

    Raises:
        ValueError: 何时抛出此异常
        RuntimeError: 何时抛出此异常

    Example:
        >>> function_name("test", 42)
        True
    """
```

## 类文档

```python
class ClassName:
    """简短的类描述.

    详细说明类的用途和职责。

    Attributes:
        attr1: 属性1的描述
        attr2: 属性2的描述
    """
```

## 检查工具

使用 pydocstyle 检查文档字符串:

```bash
pydocstyle packages/agent_core/src/agent_core/application/services/ --convention=google
```

## 规则

1. 第一行必须是简短描述，以句号结尾
2. 简短描述和详细说明之间空一行
3. 使用 Args/Returns/Raises 标记参数和返回值
4. 类型信息应在类型注解中，不在docstring中重复
5. 示例代码使用 Example: 标记
