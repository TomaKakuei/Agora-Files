import torch
from diffusers import FluxPipeline
pipe = FluxPipeline.from_pretrained("black-forest-labs/FLUX.1-schnell", torch_dtype=torch.bfloat16)
pipe = pipe.to("cuda")
try:
    pipe(prompt="Pixel art character", num_inference_steps=8, guidance_scale=0.0)
except Exception as e:
    import traceback
    traceback.print_exc()
