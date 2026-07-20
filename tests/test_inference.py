from __future__ import annotations

import json

import httpx
import numpy as np
import pytest

from frosthaven_arbiter.config import ModelSettings
from frosthaven_arbiter.inference import LlamaCppEmbeddingModel


@pytest.mark.asyncio
async def test_embedding_requests_respect_configured_batch_size() -> None:
    request_batch_sizes: list[int] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.content)["input"]
        request_batch_sizes.append(len(inputs))
        assert len(inputs) <= 2
        return httpx.Response(
            200,
            json={"data": [{"embedding": [float(value), 1.0]} for value in inputs]},
        )

    settings = ModelSettings(
        base_url="http://embedding.test/v1",
        model_path="embedding.gguf",
        timeout_seconds=5,
        batch_size=2,
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=settings.base_url)
    model = LlamaCppEmbeddingModel(settings, client)

    vectors = await model.embed(["0", "1", "2", "3", "4"])

    assert request_batch_sizes == [2, 2, 1]
    np.testing.assert_array_equal(
        vectors,
        np.array([[0.0, 1.0], [1.0, 1.0], [2.0, 1.0], [3.0, 1.0], [4.0, 1.0]], dtype=np.float32),
    )
    await client.aclose()
