"""Flex API server backed by GPT / OpenAI-compatible chat completions."""

from __future__ import annotations

from .flex_api import create_flex_app, run_flex_app
from .flex_providers import GptApiProvider


app = create_flex_app(
    GptApiProvider.from_env(),
    title="Agora GPT Flex Server",
)


if __name__ == "__main__":
    run_flex_app(app)
