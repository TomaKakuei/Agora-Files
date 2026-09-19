#!/usr/bin/env python3
"""Score prebuilt anonymous world-review packets with an OpenAI model."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agora_ui.openai_responses_client import OpenAIResponsesJsonClient
from scripts.agora_anchored_blind_world_review import (
    PROTOCOL_VERSION,
    SYSTEM_INSTRUCTION,
    response_schema,
    validate_review,
)


DEFAULT_PACKET_ROOT = (
    ROOT
    / "docs"
    / "living_world_benchmark_20260825_hidden"
    / "anchored_blind_review_pro_v0_1"
    / "packets"
)
DEFAULT_OUTPUT = (
    ROOT
    / "docs"
    / "living_world_benchmark_20260825_hidden"
    / "anchored_blind_review_sol_v0_1"
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_secret(path: Path, env_name: str) -> None:
    if os.environ.get(env_name):
        return
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"Secret file is empty: {path}")
    os.environ[env_name] = value


def client_config(
    *, model: str, api_key_env: str, thinking_level: str, endpoint_base: str
) -> dict[str, Any]:
    return {
        "openai_api": {
            "api_key_env": api_key_env,
            "endpoint_base": endpoint_base,
            "model": model,
            "temperature": 0.2,
            "max_output_tokens": 8192,
            "thinking_level": thinking_level,
            "timeout_seconds": 300,
            "retry": {
                "max_attempts": 3,
                "initial_sleep_seconds": 2.0,
                "max_sleep_seconds": 12.0,
                "backoff_multiplier": 2.0,
                "status_codes": [408, 409, 429, 500, 502, 503, 504],
            },
            "stages": {
                "anchored_blind_review": {
                    "model": model,
                    "max_output_tokens": 8192,
                    "thinking_level": thinking_level,
                }
            },
        }
    }


def normalize_auxiliary_confidence(review: dict[str, Any]) -> int:
    """Normalize an undocumented percent-style confidence without touching tiers."""
    normalized = 0
    for panel in review.get("panel_reviews") or []:
        for rating in panel.get("ratings") or []:
            value = rating.get("confidence")
            if not isinstance(value, int) or not 6 <= value <= 100:
                continue
            rating["confidence_reported"] = value
            rating["confidence_scale_inferred"] = "percent"
            rating["confidence"] = max(1, min(5, (value + 19) // 20))
            normalized += 1
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet-root", type=Path, default=DEFAULT_PACKET_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--thinking-level", default="low")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument(
        "--api-key-file",
        type=Path,
        default=Path("/home/yz_wang/.config/agora/secrets/openai_api_key"),
    )
    parser.add_argument(
        "--endpoint-base",
        default=os.environ.get("AGORA_GPT_BASE_URL", "https://api.openai.com/v1"),
    )
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()

    packet_paths = sorted(args.packet_root.glob("*.json"))
    if len(packet_paths) != 20:
        raise RuntimeError(f"Expected exactly 20 frozen packets, found {len(packet_paths)}")
    packets = [(path, load_json(path)) for path in packet_paths]
    for path, packet in packets:
        if str(packet.get("protocol")) != PROTOCOL_VERSION:
            raise ValueError(f"Unexpected protocol in {path}")

    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "protocol": PROTOCOL_VERSION,
        "experimental_only": True,
        "eligible_for_headline": False,
        "judge_model": args.model,
        "judge_identity_blind": True,
        "ranking_used": False,
        "thinking_level": args.thinking_level,
        "max_output_tokens": 8192,
        "packet_source": str(args.packet_root),
        "packet_files": [
            {"filename": path.name, "sha256": file_sha256(path)} for path in packet_paths
        ],
        "privacy": {
            "label_maps_read_by_scoring_process": False,
            "prior_reviews_read_by_scoring_process": False,
            "api_key_persisted_in_output": False,
            "store": False,
        },
        "auxiliary_confidence_normalization": {
            "rule": "1-5 unchanged; integer 6-100 mapped by ceil(value/20)",
            "quality_tier_affected": False,
            "applies_to_all_judges": True,
            "reason": "The frozen schema declared an integer but omitted a confidence range.",
        },
    }
    write_json(args.output / "scoring_manifest.json", manifest)
    (args.output / "EXPERIMENT_ONLY.md").write_text(
        "# Experimental output only\n\nThis blind-judge output does not modify the main benchmark or paper.\n",
        encoding="utf-8",
    )
    if args.prepare_only:
        print(json.dumps({"packets": len(packets), "output": str(args.output)}, indent=2))
        return

    load_secret(args.api_key_file, args.api_key_env)
    client = OpenAIResponsesJsonClient(
        client_config(
            model=args.model,
            api_key_env=args.api_key_env,
            thinking_level=args.thinking_level,
            endpoint_base=args.endpoint_base,
        )
    )
    run_history_path = args.output / "call_history" / (
        time.strftime("run_%Y%m%dT%H%M%SZ", time.gmtime()) + ".json"
    )
    for packet_path, packet in packets:
        batch_id = packet_path.stem
        review_path = args.output / "raw_reviews" / f"{batch_id}.json"
        if review_path.exists():
            validate_review(load_json(review_path), packet)
            print(f"[OPENAI_BLIND_SKIP] {batch_id}", flush=True)
            continue
        prior_invalid = sorted((args.output / "invalid_reviews").glob(f"{batch_id}_attempt_*.json"))
        if prior_invalid:
            recovered = load_json(prior_invalid[-1])
            normalized_count = normalize_auxiliary_confidence(recovered)
            if normalized_count:
                validate_review(recovered, packet)
                write_json(review_path, recovered)
                print(
                    f"[OPENAI_BLIND_RECOVER_AUX] {batch_id} "
                    f"normalized_confidence={normalized_count}",
                    flush=True,
                )
                continue
        for semantic_attempt in range(1, 3):
            print(
                f"[OPENAI_BLIND] {batch_id} semantic_attempt={semantic_attempt}",
                flush=True,
            )
            review = client.generate_json(
                system_instruction=SYSTEM_INSTRUCTION,
                prompt=json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
                schema=response_schema(),
                stage="anchored_blind_review",
            )
            normalized_count = normalize_auxiliary_confidence(review)
            write_json(run_history_path, client.call_history)
            try:
                validate_review(review, packet)
            except ValueError:
                write_json(
                    args.output
                    / "invalid_reviews"
                    / f"{batch_id}_attempt_{semantic_attempt}.json",
                    review,
                )
                if semantic_attempt >= 2:
                    raise
                continue
            write_json(review_path, review)
            if normalized_count:
                print(
                    f"[OPENAI_BLIND_AUX_NORMALIZED] {batch_id} "
                    f"confidence_fields={normalized_count}",
                    flush=True,
                )
            break
    write_json(run_history_path, client.call_history)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "valid_reviews": len(list((args.output / "raw_reviews").glob("*.json"))),
                "invalid_reviews": len(list((args.output / "invalid_reviews").glob("*.json"))),
                "transport_attempts_this_process": len(client.call_history),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
