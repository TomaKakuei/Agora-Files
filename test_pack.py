from agora_ui.world_builder.nodes.layout import pack_rooms
rooms = [{"name": f"r{i}", "width_tiles": 10, "height_tiles": 8} for i in range(25)]
try:
    print("Packing...")
    out = pack_rooms(rooms)
    print("w:", out["width_tiles"], "h:", out["height_tiles"])
except Exception as e:
    print("ERROR:", e)
