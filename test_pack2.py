from agora_ui.world_builder.nodes.layout import pack_rooms
rooms = [{"name": f"r{i}", "width_tiles": 10, "height_tiles": 8} for i in range(25)]
out = pack_rooms(rooms)
print([(r["name"], r.get("x_pos"), r.get("y_pos")) for r in out["rooms"][:5]])
