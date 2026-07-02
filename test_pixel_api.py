from pathlib import Path
from macro_ui.serve_macro_ui import _package_export_dir, read_world_package_metadata, _metadata_bool, _pixel_world_workspace, _metadata_json, load_world_config_from_access_code, MACRO_PACKAGE_ROOT
import sys

normalized = "178a8929d63f4497"
export_dir = _package_export_dir(normalized)
package_db = export_dir / "world_package.db"
print("package_db exists:", package_db.is_file())
package_meta = read_world_package_metadata(package_db)
pixel_read = _metadata_bool(package_meta, "pixel_read")
print("pixel_read:", pixel_read)
startup_ok = _metadata_bool(package_meta, "startup_ok")
print("startup_ok:", startup_ok)
workspace = _pixel_world_workspace(normalized)
report = _metadata_json(package_meta, "pixel_read_report")
print("report is None:", report is None)
config, metadata = load_world_config_from_access_code(MACRO_PACKAGE_ROOT, normalized, materialize_dir=workspace)
print("metadata['startup_ok']:", metadata.get("startup_ok", False))
has_startup_ok = "startup_ok" in metadata
print("has_startup_ok:", has_startup_ok)
