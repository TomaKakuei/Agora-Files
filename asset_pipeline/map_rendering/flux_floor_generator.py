import os
from pathlib import Path
from typing import Any, Dict, List
import requests
import time
from PIL import Image

# FLUX endpoint configuration
FLUX_ENDPOINT = "http://127.0.0.1:8135/generate"

def generate_flux_floor(
    room: Dict[str, Any], 
    output_dir: Path,
    provider: Any = None,
    tile_px: int = 32
) -> str:
    """
    Generate a room-scale top-down plate using FLUX2 and downscale using
    nearest-neighbor so it fits the authored room footprint exactly.
    """
    room_id = room.get("room_id", "unknown_room")
    room_name = str(room.get("name", room_id) or room_id).strip()
    purpose = str(((room.get("metadata") or {}).get("purpose") if isinstance(room.get("metadata"), dict) else "") or "").strip()
    visual = room.get("visual", {}) if isinstance(room.get("visual", {}), dict) else {}
    decor_tags = ", ".join(str(tag).strip() for tag in visual.get("decor_tags", []) if str(tag).strip())
    base_prompt = (
        room.get("room_scene_prompt")
        or room.get("flux_floor_prompt")
        or "pixel art room floor texture"
    )
    w_tiles = int(room.get("width_tiles", 5))
    h_tiles = int(room.get("height_tiles", 5))
    
    # Calculate aspect ratio
    aspect = w_tiles / h_tiles
    
    # Typical FLUX max dimension is 1024, so let's scale it while keeping aspect ratio
    if aspect >= 1.0:
        flux_w = 1024
        flux_h = int(1024 / aspect)
    else:
        flux_h = 1024
        flux_w = int(1024 * aspect)
        
    # Ensure they are multiples of 32 (often required by image models)
    flux_w = (flux_w // 32) * 32
    flux_h = (flux_h // 32) * 32

    # The actual FLUX call (using our compositor fallback which wraps vertex/flux logic)
    # Note: If generate_image_with_fallback doesn't support width/height, we might need a custom call.
    # For now we pass width/height as kwargs if the underlying client supports it, 
    # but the primary prompt is what matters for the style.
    # To enforce the LORA pixel art, we append our trigger words just in case.
    full_prompt = (
        f"{base_prompt}, "
        f"room name: {room_name}, "
        f"purpose: {purpose or 'room interaction space'}, "
        f"decor cues: {decor_tags or 'readable room props'}, "
        "top-down / isometric room plate, no labels, no visible text, "
        "crunchy pixel art, readable tile-friendly layout, "
        "single coherent room overview, floor and fixture identity preserved"
    )
    
    out_path = output_dir / f"floor_{room_id}.png"
    if out_path.exists():
        if out_path.stat().st_size > 1024:
            try:
                # Check if it's a solid gray image
                with Image.open(out_path) as img:
                    mean = sum(img.convert('L').getdata()) / (img.width * img.height)
                    if abs(mean - 128) > 5:
                        return str(out_path)
            except Exception:
                pass
        out_path.unlink(missing_ok=True)

    print(f"Generating FLUX floor for room {room_id} ({w_tiles}x{h_tiles} tiles). Native res: {flux_w}x{flux_h}")
    # We call the generation (assuming the client can parse width/height if we pass it, 
    # or it generates 1024x1024 and we crop/resize it later)
    # For robust integration we just use the prompt and then rigorously resize.
    temp_img_path = output_dir / f"temp_{room_id}.png"
    
    # Check FLUX health first
    try:
        health_resp = requests.get(FLUX_ENDPOINT.replace("/generate", "/health"), timeout=5)
        health_resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"FLUX service is DOWN or unreachable at {FLUX_ENDPOINT}: {e}")

    # Make request to the local FLUX service with retry
    max_retries = 1
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                FLUX_ENDPOINT,
                json={
                    "prompt": full_prompt,
                    "width": flux_w,
                    "height": flux_h,
                    "steps": 8,
                    "asset_kind": "map_asset",
                    "output_path": str(temp_img_path)
                },
                timeout=600
            )
            resp.raise_for_status()
            break
        except Exception as e:
            if attempt < max_retries:
                print(f"Error calling FLUX service, retrying: {e}")
                time.sleep(2)
            else:
                raise RuntimeError(f"FLUX generation failed for {room_id} after {max_retries} retries: {e}")
    
    if not temp_img_path.exists():
        raise RuntimeError(f"FLUX service returned OK but {temp_img_path} was not created.")
    
    img = Image.open(temp_img_path).convert("RGB")
    temp_img_path.unlink(missing_ok=True)
        
    # [CRITICAL REQUIREMENT]
    # Downscale strictly to (width_tiles * tile_px) x (height_tiles * tile_px) using NEAREST
    final_w = w_tiles * tile_px
    final_h = h_tiles * tile_px
    
    # We first crop to exact aspect ratio if FLUX didn't respect the requested dimensions
    actual_aspect = img.width / img.height
    target_aspect = final_w / final_h
    
    if abs(actual_aspect - target_aspect) > 0.05:
        # Crop center
        if actual_aspect > target_aspect:
            # Image is too wide
            new_w = int(img.height * target_aspect)
            left = (img.width - new_w) // 2
            img = img.crop((left, 0, left + new_w, img.height))
        else:
            # Image is too tall
            new_h = int(img.width / target_aspect)
            top = (img.height - new_h) // 2
            img = img.crop((0, top, img.width, top + new_h))
            
    img = img.resize((final_w, final_h), resample=Image.NEAREST)
    img.save(out_path)
    return str(out_path)

def generate_all_floors(config: Dict[str, Any], output_dir: Path, provider: Any = None):
    output_dir.mkdir(parents=True, exist_ok=True)
    rooms = config.get("space", {}).get("rooms", [])
    for room in rooms:
        generate_flux_floor(room, output_dir, provider)
