from PIL import Image, ImageDraw

from asset_pipeline.agent_assets.clients import (
    _align_foreground_hue,
    _compact_sprite_proportions,
    _flat_border_summary,
    _flux2_identity_edit_prompt,
    _flux_sprite_prompt,
    _natural_walk_cycle,
    _remove_flat_border_background,
)
from asset_pipeline.generate_world_asset_set_full import _direction_mirror_evidence


def test_flux_prompt_keeps_identity_and_scene_guards_inside_short_window():
    prompt = _flux_sprite_prompt(
        prompt_bundle={
            "display_name": "Archivist Varnum Kell",
            "gender_presentation": "feminine",
            "sprite_prompt": (
                "Role identity: Chief Censor of the Sluicegate. "
                "Character wears Cupric fungicide pressurized chest canister, "
                "carries Calcified lead quarantine stamp, and follows silhouette rule: "
                "Stiff rigid top-heavy orthogonal silhouette with wide collar. "
                "Wardrobe includes a heavy leather spore-respirator."
            ),
        },
        direction="Left-facing profile walk, rear boot extended left",
        readable_palette="#526762, #7BF0B3, #A2ADA7",
    )

    assert len(prompt.split()) <= 70
    assert "Chief Censor" in prompt
    assert "Cupric fungicide" in prompt
    assert "same hooded respirator" in prompt
    assert "#526762 #7BF0B3 clothes" in prompt
    assert "Calcified lead quarantine stamp" not in prompt
    assert "No backpack, carried object, text, scenery, shadow, duplicate" in prompt
    assert "ONE unarmed feminine adult Chief Censor" in prompt
    assert "short thick legs" in prompt
    assert "Chunky JRPG pixel sprite" in prompt


def test_flux2_edit_prompt_limits_change_to_pose_and_view():
    prompt = _flux2_identity_edit_prompt("Strict left side-profile walk.")

    assert prompt.endswith("Strict left side-profile walk.")
    assert "Preserve the exact face" in prompt
    assert "clothing" in prompt
    assert "Change only pose and view" in prompt


def test_compact_proportion_transform_targets_only_tall_figures():
    image = Image.new("RGBA", (60, 180), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((17, 0, 43, 36), fill=(205, 155, 115, 255))
    draw.rectangle((9, 32, 51, 108), fill=(150, 45, 50, 255))
    draw.rectangle((15, 104, 28, 174), fill=(45, 48, 55, 255))
    draw.rectangle((32, 104, 45, 174), fill=(45, 48, 55, 255))

    compacted, metrics = _compact_sprite_proportions(image, target_aspect=0.60)

    assert metrics["source_aspect"] < 0.40
    assert metrics["compact_severity"] > 0.9
    assert metrics["leg_vertical_scale"] < 0.80
    assert metrics["head_width_scale"] > 1.10
    assert compacted.width / compacted.height > metrics["source_aspect"]


def test_compact_proportion_transform_leaves_already_broad_figure_alone():
    image = Image.new("RGBA", (72, 108), (50, 80, 120, 255))

    compacted, metrics = _compact_sprite_proportions(image, target_aspect=0.60)

    assert compacted.size == image.size
    assert metrics["compact_severity"] == 0.0
    assert metrics["leg_vertical_scale"] == 1.0


def test_natural_walk_cycle_reverses_stride_without_flipping_torso():
    character = Image.new("RGBA", (112, 112), (0, 0, 0, 0))
    draw = ImageDraw.Draw(character)
    draw.rectangle((36, 10, 75, 72), fill=(160, 45, 55, 255))
    draw.rectangle((29, 67, 50, 108), fill=(45, 50, 60, 255))
    draw.rectangle((59, 67, 83, 101), fill=(60, 70, 85, 255))
    draw.rectangle((27, 103, 54, 110), fill=(20, 25, 30, 255))
    draw.rectangle((61, 96, 91, 104), fill=(20, 25, 30, 255))

    frames = _natural_walk_cycle(character)

    assert len(frames) == 4
    assert frames[0].crop((0, 0, 112, 66)).tobytes() == frames[2].crop((0, 0, 112, 66)).tobytes()
    assert frames[0].crop((0, 75, 112, 112)).tobytes() != frames[2].crop((0, 75, 112, 112)).tobytes()
    assert frames[1].tobytes() != frames[0].tobytes()
    assert frames[3].tobytes() != frames[2].tobytes()


def test_flat_nonwhite_background_is_removed_from_edges_only():
    image = Image.new("RGB", (64, 64), (37, 35, 38))
    draw = ImageDraw.Draw(image)
    draw.rectangle((25, 8, 39, 55), fill=(30, 32, 35))
    draw.rectangle((28, 15, 36, 50), fill=(210, 220, 215))

    summary = _flat_border_summary(image)
    isolated = _remove_flat_border_background(image)

    assert summary["flat_border_ratio"] == 1.0
    assert isolated.getpixel((0, 0))[3] == 0
    assert isolated.getpixel((30, 20))[3] == 255
    assert isolated.getpixel((26, 20))[3] == 255


def test_conditioned_pose_hue_is_aligned_to_canonical_clothing():
    reference = Image.new("RGB", (64, 64), (220, 220, 220))
    source = Image.new("RGB", (64, 64), (220, 220, 220))
    ImageDraw.Draw(reference).rectangle((22, 14, 42, 56), fill=(115, 30, 150))
    ImageDraw.Draw(source).rectangle((22, 14, 42, 56), fill=(180, 105, 25))

    aligned, shift = _align_foreground_hue(source, reference)
    red, green, blue, _ = aligned.getpixel((30, 40))

    assert abs(shift) > 20
    assert blue > green
    assert red > green


def test_direction_evidence_requires_exact_mirror_and_asymmetric_pose(tmp_path):
    sheet = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    for column in range(4):
        left = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        ImageDraw.Draw(left).rectangle((12, 12, 62, 116), fill=(40, 180, 120, 255))
        sheet.alpha_composite(left, (column * 128, 256))
        sheet.alpha_composite(left.transpose(Image.Transpose.FLIP_LEFT_RIGHT), (column * 128, 384))
    raw_path = tmp_path / "raw_character_128.png"
    sheet.save(raw_path)

    evidence = _direction_mirror_evidence({"asset_bundle_path": str(tmp_path / "asset_bundle.json")})

    assert evidence["pass"] is True
    assert evidence["maximum_mirror_mismatch_ratio"] == 0.0
    assert evidence["minimum_left_row_asymmetry_ratio"] >= 0.08
