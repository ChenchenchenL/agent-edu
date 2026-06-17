"""测试审计类型定义."""
from agent_core.domain.schemas.audit_types import RequestAuditMetadata


def test_request_audit_metadata_structure():
    """测试RequestAuditMetadata结构."""
    metadata: RequestAuditMetadata = {
        "path": "/api/tasks",
        "method": "POST",
        "client_host": "192.168.1.1",
    }

    assert metadata["path"] == "/api/tasks"
    assert metadata["method"] == "POST"
    assert metadata["client_host"] == "192.168.1.1"


def test_request_audit_metadata_optional_fields():
    """测试可选字段."""
    metadata: RequestAuditMetadata = {
        "path": "/api/tasks",
        "method": "GET",
        "client_host": "localhost",
    }

    assert metadata["client_host"] == "localhost"
