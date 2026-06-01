import httpx

from agent_core.infrastructure.embedding.dashscope_compatible_provider import (
    DashScopeCompatibleEmbeddingProvider,
)


async def test_embed_texts_returns_vectors(monkeypatch):
    provider = DashScopeCompatibleEmbeddingProvider(
        api_key="secret",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="text-embedding-v4",
        timeout_seconds=30.0,
        dimensions=1024,
    )
    captured = {}

    async def fake_post(self, url, *, headers, json):
        captured["url"] = url
        captured["payload"] = json
        request = httpx.Request("POST", f"{self.base_url}{url}")
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]},
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    vectors = await provider.embed_texts(["first", "second"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert captured["url"] == "/embeddings"
    assert captured["payload"]["model"] == "text-embedding-v4"
    assert captured["payload"]["dimensions"] == 1024
