#!/usr/bin/env python3
"""
Agora Benchmark Evaluator - Rigorous Academic Standard
Implements AgentSLABench, HackDetect (Mislead Gap), ECP (Trajectory Validation),
and SkillTV-Bench (Evidence-Grounded Verification).
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Budgets for AgentSLABench
TIME_BUDGET_SECONDS = 1800  # 30 minutes


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def calculate_easr(success_rate: float, wall_time_sec: float) -> float:
    """AgentSLABench EASR Formula."""
    if wall_time_sec <= 0:
        return 0.0 # Missing observability is a SLA failure
    time_penalty = min(1.0, TIME_BUDGET_SECONDS / wall_time_sec)
    # Without token logs, we just apply the time penalty
    return success_rate * time_penalty


def evaluate_world(access_code: str, repo_root: Path) -> dict:
    package_dir = repo_root / "output" / "package_exports" / access_code
    meta_path = package_dir / "package_meta.json"
    
    if not meta_path.is_file():
        return {"error": f"package_meta.json not found for {access_code}"}

    meta = _read_json(meta_path)
    draft_id = meta.get("world_creator_draft_id")
    revision_id = meta.get("world_creator_revision")

    if not draft_id or not revision_id:
        return {"error": "Could not extract draft_id or revision_id from package_meta.json"}

    revision_dir = repo_root / "output" / "world_creator_drafts" / draft_id / "revisions" / revision_id
    
    # 1. Trajectory Extraction (ECP / HAL)
    status_path = revision_dir / "status.json"
    compiler_path = revision_dir / "compiler_report.json"
    request_path = revision_dir / "generation_request.json"
    db_path = revision_dir / "world_package.db"

    status_data = _read_json(status_path)
    compiler_data = _read_json(compiler_path)
    request_data = _read_json(request_path)

    # 2. AgentSLABench (EASR) Profiling
    wall_time_sec = 0.0
    
    # Try draft manifest first for full execution time
    manifest_path = repo_root / "output" / "world_creator_drafts" / draft_id / "draft_manifest.json"
    manifest_data = _read_json(manifest_path)
    if manifest_data:
        created_str = manifest_data.get("created_at")
        updated_str = manifest_data.get("updated_at")
    else:
        created_str = status_data.get("created_at")
        updated_str = status_data.get("updated_at")
    
    if created_str and updated_str:
        try:
            fmt = "%Y-%m-%dT%H:%M:%S"
            # Strip timezone for simple delta if present
            c = datetime.strptime(created_str[:19], fmt)
            u = datetime.strptime(updated_str[:19], fmt)
            wall_time_sec = (u - c).total_seconds()
        except Exception as e:
            pass
            
    # If wall time is exactly 0 due to same timestamps, assume a minimal baseline to avoid instant zeroing,
    # OR since AgentSLABench penalizes lack of observability, we leave it at 0.
    # However, if it took time, it will be accurately logged.
    # Success definition: did the package materialize?
    base_success = 1.0 if status_data.get("package_validation", {}).get("materialize_ok", False) else 0.0
    easr_score = calculate_easr(base_success, wall_time_sec)

    # 3. HackDetect (Mislead Gap / Exploit Detection)
    exploit_detected = False
    exploit_reason = ""
    compiler_errors = compiler_data.get("errors", [])
    if compiler_errors and base_success > 0:
        exploit_detected = True
        exploit_reason = "Compiler had errors but package was marked as successful (swallowed exception)."
    
    stage_reports = compiler_data.get("stage_reports", {})
    for stage, report in stage_reports.items():
        if not report.get("ok", False) and base_success > 0:
            exploit_detected = True
            exploit_reason = f"Stage {stage} failed but package materialized (swallowed exception)."

    # 4. SkillTV-Bench (Evidence-Grounded Verification)
    target_agent_count = request_data.get("request", {}).get("agent_count_target", 0)
    
    # Count materialized agent packages (character_atlas pairs) as empirical evidence
    actual_agent_count = 0
    assets_dir = package_dir / "materialized" / "assets" / "generated"
    if assets_dir.is_dir():
        for path in assets_dir.glob("*/*"):
            if (path / "character_atlas.png").is_file() and (path / "character_atlas.json").is_file():
                actual_agent_count += 1
                
    evidence_score = 1.0 if actual_agent_count >= target_agent_count and target_agent_count > 0 else 0.0
    if actual_agent_count < target_agent_count:
        evidence_penalty = f"Requested {target_agent_count} agents but only generated {actual_agent_count}."
    else:
        evidence_penalty = "None"

    # Compute Final Academic Benchmark Score
    # Base is EASR (0-100)
    final_score = easr_score * 100
    
    # Penalize if evidence does not ground intent
    if evidence_score == 0.0:
        final_score -= 50
        
    # Fatal penalty if exploit detected
    if exploit_detected:
        final_score = 0.0
        
    return {
        "access_code": access_code,
        "draft_id": draft_id,
        "revision_id": revision_id,
        "metrics": {
            "wall_time_sec": wall_time_sec,
            "base_success": base_success,
            "easr_score": easr_score,
            "target_agent_count": target_agent_count,
            "actual_agent_count": actual_agent_count,
            "evidence_grounded": evidence_score == 1.0,
            "exploit_detected": exploit_detected,
        },
        "penalties": {
            "evidence_penalty": evidence_penalty,
            "exploit_reason": exploit_reason
        },
        "final_academic_score": max(0.0, final_score)
    }

def main():
    parser = argparse.ArgumentParser(description="Academic Standard Agora Benchmark Evaluator")
    parser.add_argument("--access-code", required=True, help="Access code of the published world to evaluate.")
    parser.add_argument("--repo-root", default=".", help="Root directory of the Agora 2.0 repository.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    result = evaluate_world(args.access_code, repo_root)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
