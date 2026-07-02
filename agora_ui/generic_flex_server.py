"""Config-driven Flex API server for generic HTTP providers."""

from __future__ import annotations

from .flex_api import create_flex_app, run_flex_app
from .flex_providers import GenericApiProvider


app = create_flex_app(
    GenericApiProvider.from_env(),
    title="Agora Generic Flex Server",
)


if __name__ == "__main__":
    run_flex_app(app)
