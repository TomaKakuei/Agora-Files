from pathlib import Path
from agora_ui.package_db import pack_world_package
package_root = Path("/home/yz_wang/yz_main/agora_2.0/output/package_exports/3bb232f739244202")
pack_world_package(
    source_root=package_root / "materialized",
    output_db=package_root / "live_state.db"
)
