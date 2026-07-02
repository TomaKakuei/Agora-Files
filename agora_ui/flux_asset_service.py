#!/usr/bin/env python3
"""Simple local FLUX asset service for heavy pixel-oriented asset generation."""

from __future__ import annotations

import argparse
import base64
import io
import logging
import os
import sys
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from PIL import Image


LOGGER = logging.getLogger("agora.flux_asset_service")


def _disable_broken_xformers_import() -> None:
    """Avoid importing an incompatible xformers build from the shared runtime env."""
    if "xformers" not in sys.modules:
        sys.modules["xformers"] = None
    if "xformers.ops" not in sys.modules:
        sys.modules["xformers.ops"] = None


_disable_broken_xformers_import()

try:
    import torch
    from diffusers import FluxPipeline, FluxImg2ImgPipeline
except Exception:  # pragma: no cover
    torch = None
    FluxPipeline = None
    FluxImg2ImgPipeline = None


class FluxAssetRequest(BaseModel):
    prompt: str = Field(min_length=1)
    negative_prompt: str = ""
    width: int = Field(default=512, ge=128, le=2048)
    height: int = Field(default=512, ge=128, le=2048)
    steps: int = Field(default=8, ge=1, le=64)
    guidance_scale: float = Field(default=0.0, ge=0.0, le=20.0)
    seed: int | None = None
    output_path: str = ""
    return_base64: bool = False
    asset_kind: Literal["agent_sheet", "map_asset", "room_prop", "generic"] = "generic"
    init_image_base64: str | None = None
    strength: float = Field(default=0.85, ge=0.0, le=1.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8135)
    parser.add_argument("--model", default=os.environ.get("AGORA_FLUX_MODEL", "black-forest-labs/FLUX.1-schnell"))
    parser.add_argument("--device", default=os.environ.get("AGORA_FLUX_DEVICE", "cuda"))
    parser.add_argument("--dtype", default=os.environ.get("AGORA_FLUX_DTYPE", "bfloat16"))
    return parser.parse_args()


class FluxService:
    def __init__(self, *, model_name: str, device: str, dtype_name: str) -> None:
        self.model_name = model_name
        self.device = device
        self.dtype_name = dtype_name
        self._pipeline = None
        self._img2img_pipeline = None

    def _torch_dtype(self):
        if torch is None:
            raise RuntimeError("torch is not available in this environment")
        return {
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }.get(self.dtype_name, torch.bfloat16)

    def _load(self):
        if self._pipeline is not None:
            return self._pipeline
        if FluxPipeline is None:
            raise RuntimeError("diffusers FLUX pipeline is unavailable")
        
        LOGGER.info("Loading base FLUX pipeline...")
        pipe = FluxPipeline.from_pretrained(self.model_name, torch_dtype=self._torch_dtype())
        
        LOGGER.info("Loading Pixel Art LoRA...")
        try:
            pipe.load_lora_weights("Shakker-Labs/FLUX.1-Kontext-dev-LoRA-Pixel-Style")
            LOGGER.info("LoRA loaded successfully.")
        except Exception as e:
            LOGGER.error(f"Failed to load LoRA: {e}")
            
        if hasattr(pipe, "to"):
            pipe = pipe.to(self.device)
            
        LOGGER.info("Creating Img2Img pipeline from components...")
        self._img2img_pipeline = FluxImg2ImgPipeline(**pipe.components)
            
        self._pipeline = pipe
        return pipe

    def generate(self, request: FluxAssetRequest) -> Image.Image:
        self._load()
        generator = None
        if request.seed is not None and torch is not None:
            generator = torch.Generator(device="cpu").manual_seed(int(request.seed))
            
        if request.init_image_base64:
            LOGGER.info("Using Image-to-Image pipeline")
            init_img_bytes = base64.b64decode(request.init_image_base64)
            init_image = Image.open(io.BytesIO(init_img_bytes)).convert("RGB").resize((request.width, request.height))
            
            invoke_kwargs = {
                "prompt": request.prompt,
                "image": init_image,
                "strength": request.strength,
                "num_inference_steps": request.steps,
                "guidance_scale": request.guidance_scale,
                "generator": generator,
            }
            result = self._img2img_pipeline(**invoke_kwargs)
        else:
            LOGGER.info("Using Text-to-Image pipeline")
            invoke_kwargs = {
                "prompt": request.prompt,
                "width": request.width,
                "height": request.height,
                "num_inference_steps": request.steps,
                "guidance_scale": request.guidance_scale,
                "generator": generator,
            }
            result = self._pipeline(**invoke_kwargs)
            
        return result.images[0]


args = parse_args()
service = FluxService(model_name=args.model, device=args.device, dtype_name=args.dtype)
app = FastAPI(title="Agora FLUX Asset Service")


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "model": service.model_name,
        "device": service.device,
        "dtype": service.dtype_name,
        "pipeline_loaded": service._pipeline is not None,
    }


@app.post("/generate")
def generate(request: FluxAssetRequest) -> dict[str, object]:
    try:
        image = service.generate(request)
    except Exception as exc:
        LOGGER.exception("FLUX generation failed for asset_kind=%s output_path=%s", request.asset_kind, request.output_path)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    output_path = str(request.output_path).strip()
    if output_path:
        path = Path(output_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
    payload = {
        "status": "ok",
        "asset_kind": request.asset_kind,
        "width": image.width,
        "height": image.height,
        "output_path": output_path,
    }
    if request.return_base64:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        payload["image_base64"] = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return payload


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=args.bind, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
