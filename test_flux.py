import requests
import json
payload = {
    "prompt": "Pixel art character sprite sheet",
    "width": 512,
    "height": 512,
    "steps": 4,
    "output_path": "/home/yz_wang/yz_main/Agora_UI_Run/test_flux_out.png",
    "asset_kind": "agent_sheet",
    "return_base64": False
}
resp = requests.post("http://127.0.0.1:8135/generate", json=payload)
print(resp.status_code, resp.text)
