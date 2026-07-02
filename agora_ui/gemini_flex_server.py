"""Flex API server backed by Gemini AI Studio REST."""

from __future__ import annotations

from .flex_api import create_flex_app, run_flex_app
from .flex_providers import GeminiAIStudioProvider


app = create_flex_app(
    GeminiAIStudioProvider.from_env(),
    title="Agora Gemini AI Studio Flex Server",
)


if __name__ == "__main__":
    run_flex_app(app)
