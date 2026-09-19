from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from asset_pipeline.agent_assets import clients


def test_unknown_sprite_adapter_fails_without_renderer_substitution(tmp_path: Path) -> None:
    with patch.object(clients, "_request_flux_sheet") as flux_request, patch.object(
        clients, "_request_sd_sheet"
    ) as sd_request:
        with pytest.raises(ValueError, match="Unsupported sprite_generation.adapter"):
            clients._request_sprite_summary(
                world_config={},
                pipeline_config={"sprite_generation": {"adapter": "unknown_renderer"}},
                prompt_bundle={},
                output_dir=tmp_path,
                raw_sheet_path=tmp_path / "raw.png",
            )

    flux_request.assert_not_called()
    sd_request.assert_not_called()


def test_sd_webui_adapter_requires_explicit_selection(tmp_path: Path) -> None:
    expected = {"status": "ok", "adapter": "sd_webui_txt2img"}
    with patch.object(clients, "_request_sd_sheet", return_value=expected) as sd_request:
        result = clients._request_sprite_summary(
            world_config={},
            pipeline_config={"sprite_generation": {"adapter": " SD_WEBUI_TXT2IMG "}},
            prompt_bundle={},
            output_dir=tmp_path,
            raw_sheet_path=tmp_path / "raw.png",
        )

    assert result == expected
    sd_request.assert_called_once()
