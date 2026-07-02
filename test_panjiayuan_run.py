import sys
from pathlib import Path
from agora_ui.world_builder.core import create_draft

request = {
    "world_name": "Panjiayuan Market Run 6",
    "genre": "realistic antique market",
    "brief": "潘家园旧货市场. A dense antique market of stalls, appraisers, rumors, and provenance disputes. Boutique logic: exactly 25 main characters. Map: exactly 7 rooms, dimensions between 3x4 and 10x8.",
    "agent_count_target": 25,
    "player_count_target": 4
}

package_root = Path("/home/yz_wang/yz_main/agora_2.0")

try:
    status = create_draft(package_root=package_root, request=request)
    print(status)
except Exception as e:
    import traceback
    traceback.print_exc()
