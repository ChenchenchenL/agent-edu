"""审计相关的类型定义."""
try:
    from typing import TypedDict
except ImportError:
    # Python 3.6 fallback - use regular dict with type hints in docstring
    TypedDict = dict


class RequestAuditMetadata(TypedDict):
    """HTTP请求审计元数据.

    替代 dict[str, Any] 提供类型安全。

    Fields:
        path (str): 请求路径
        method (str): HTTP方法
        client_host (str): 客户端主机
    """
    pass


# Python 3.6兼容的类型定义
def create_request_audit_metadata(path, method, client_host):
    """创建请求审计元数据.

    Args:
        path: 请求路径
        method: HTTP方法
        client_host: 客户端主机

    Returns:
        包含审计元数据的字典
    """
    return {
        "path": path,
        "method": method,
        "client_host": client_host,
    }

