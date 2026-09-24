"""Flex API server backed by Vertex AI."""

from __future__ import annotations

from .flex_api import create_flex_app, run_flex_app
from .flex_providers import VertexAIProvider


app = create_flex_app(
    VertexAIProvider.from_env(),
    title="Agora Vertex Flex Server",
)


if __name__ == "__main__":
    run_flex_app(app)
