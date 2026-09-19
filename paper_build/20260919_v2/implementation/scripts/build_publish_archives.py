#!/usr/bin/env python3
"""Build sanitized full-stack and lean-core Agora publication archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import tarfile
from pathlib import Path
from typing import Callable, Iterable


RELEASE_DATE = "2026-07-30"
RELEASE_ID = "20260730"
TEXT_SUFFIXES = {
    "",
    ".cfg",
    ".cff",
    ".css",
    ".env",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".sh",
    ".tex",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
COMMON_REJECTED_PARTS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
}
COMMON_REJECTED_SUFFIXES = {
    ".bak",
    ".log",
    ".pyc",
    ".pyo",
    ".tmp",
}
SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"sk-[0-9A-Za-z_-]{16,}"),
    re.compile(r"ghp_[0-9A-Za-z]{20,}"),
    re.compile(r"github_pat_[0-9A-Za-z_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
]


FULL_SCRIPT_ALLOWLIST = {
    "_playwright_firefox.py",
    "agora_benchmark_collect.py",
    "agora_benchmark_quality_ablation.py",
    "agora_benchmark_runtime_collect.py",
    "agora_build_paper_evidence_summary.py",
    "agora_decomposed_controlled_baseline.py",
    "agora_extract_qualitative_cases.py",
    "agora_headless_agent_latency_batch.py",
    "agora_headless_message_latency_batch.py",
    "agora_make_one_sentence_paper_figures.py",
    "agora_monolithic_baseline.py",
    "agora_objective_world_quality_eval.py",
    "agora_one_sentence_world_audit.py",
    "agora_paper_cost_analysis.py",
    "agora_seeded_fault_benchmark.py",
    "agora_seeded_local_retry_experiment.py",
    "agora_strict_multimodal_audit.py",
    "assert_db.py",
    "capture_creator_regression.sh",
    "creator_frontend_full_pipeline.py",
    "headless_pixel_firefox_regression.py",
    "launch_flux_asset_service.sh",
    "pixel_live_load_test.py",
    "probe_live_boot.py",
    "publish_draft.py",
    "run_benchmark_runtime_batch.py",
    "run_benchmark_world_batch.py",
}

CORE_MODULE_FILES = {
    "__init__.py",
    "adjudicator_schemas.py",
    "boundary_schemas.py",
    "extra_world_functions.py",
    "flex_api.py",
    "flex_client.py",
    "foundation_schemas.py",
    "jsonc_utils.py",
    "package_db.py",
    "package_schemas.py",
    "scenario_schemas.py",
    "world_definition.py",
    "world_pipeline.py",
}

EVIDENCE_FILES = {
    "headless_message_latency_summary.json",
    "headless_message_latency_summary.md",
    "paper_cost_analysis_20260729.json",
    "paper_cost_analysis_20260729.md",
    "paper_evidence_summary_20260729.json",
    "paper_evidence_summary_20260729.md",
    "runtime_evaluation_summary.json",
    "runtime_evaluation_summary.md",
    "seeded_fault_benchmark_20260729.json",
    "seeded_fault_benchmark_20260729.md",
}

EVIDENCE_NESTED_FILES = {
    "decomposed_controlled_low_20260729/decomposed_controlled_summary.json",
    "decomposed_controlled_low_heldout_20260729/decomposed_controlled_summary.json",
    "monolithic_baseline_low_24k_quality_20260729/monolithic_baseline_summary.json",
    "monolithic_baseline_low_24k_quality_heldout_20260729/monolithic_baseline_summary.json",
    "objective_quality_combined10_20260729/objective_world_quality.json",
    "objective_quality_heldout_20260729/objective_world_quality.json",
    "seeded_local_retry_20260729/seeded_local_retry_summary.json",
}


FULL_README = """# Agora

**One Sentence, One Executable World**

This is the sanitized full-stack snapshot from the internal Agora 2.0 release
line. It contains the typed world compiler, specialist generation pipeline,
FLUX asset pipeline, package database, authoring UI, Pixel runtime, REST and
WebSocket services, validation tools, tests, and the paper artifact.

## System Boundary

- Natural-language authoring compiles into specialist-owned typed IR.
- `world_config.json` and scenario JSON are the editable source layer.
- `world_package.db` is the portable runtime bundle and source of truth.
- FLUX is the active raster renderer; Gemini/Vertex direct raster generation
  is disabled.
- Draft generation and art run as revision-addressed detached workers.
- Published worlds use REST for state/actions and WebSocket for movement.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
pytest -q
python -m macro_ui.serve_macro_ui --bind 127.0.0.1 --port 8125
```

The creator is served at `/creator`, the operational UI at `/macro`, and the
live Pixel client at `/pixel`.

World and art generation require provider credentials and a separately running
FLUX service. No credentials, model weights, generated runtime history, or
private deployment units are included in this archive.

## Paper

The final paper PDF, source, figures, and compact evidence bundle are under
[`paper/`](paper/). The public project name is **Agora**; “2.0” identifies this
full-stack release line only.

## Repository Split

`Agora-2.0` is the runnable integration archive. `Agora-C` is the lean
compiler/runtime-contract archive and intentionally excludes frontend,
deployment, browser validation, and image-generation operations.

See [RELEASE_NOTES.md](RELEASE_NOTES.md),
[PUBLICATION_CHECKLIST.md](PUBLICATION_CHECKLIST.md),
[VALIDATION_REPORT.md](VALIDATION_REPORT.md), and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
"""


CORE_README = """# Agora-C

**Lean compiler and runtime contracts for Agora**

Agora-C is the compact companion artifact for **Agora: One Sentence, One
Executable World**. It preserves the portable contracts that make a generated
world inspectable and replayable without duplicating the operational product.

## Included

- typed semantic, scenario, package, and runtime schemas
- registered world-definition and compiler contracts
- SQLite `world_package.db` pack/materialize helpers
- JSON-declared orchestration defaults and execution engine
- universal adjudication logic and Flex request contracts
- a reference package and deployment-independent core tests

## Intentionally Excluded

- FastAPI product routing and live WebSocket management
- Macro, Creator, and Pixel frontends
- systemd and Cloudflare deployment
- FLUX services and heavy art/QA pipelines
- browser harnesses, generated assets, logs, and experiment history

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest -q
```

The reference package is under `examples/reference_world/`. The full runnable
system and paper evaluation scripts are distributed in the paired
`Agora-2.0` archive.

See [ARCHITECTURE.md](ARCHITECTURE.md),
[RELEASE_NOTES.md](RELEASE_NOTES.md),
[VALIDATION_REPORT.md](VALIDATION_REPORT.md), and
[PUBLICATION_CHECKLIST.md](PUBLICATION_CHECKLIST.md).
"""


CORE_ARCHITECTURE = """# Agora-C Architecture

Agora-C records the portable contract shared with the runnable Agora stack.

## 1. Authoring Contract

World semantics originate in JSON and are normalized through registered
schemas and policy registries. Python executes declared behavior; it does not
own world-specific themes.

## 2. Typed World Compilation

`world_pipeline.py` and `world_definition.py` resolve semantic entities,
relations, policies, and frontend-independent world definitions. Pydantic
schemas define the boundaries used by generation, packaging, adjudication, and
runtime state.

## 3. Runtime Bundle

`package_db.py` compiles a world workspace into `world_package.db`, materializes
it back into files, and preserves structured world-definition tables. The
package is the portable runtime boundary.

## 4. Orchestration

`agora_ui/runtime/` compiles JSON-declared phases, components, policies, and
operations into an executable plan. The engine is independent of web serving.

## 5. Adjudication

`agora_ui/universal_adjudicator/` applies typed movement, item, custom-action,
and media intents against explicit state. Flex request models provide a
provider-neutral inference boundary.

## Full-Stack Boundary

The paired Agora-2.0 archive owns authoring APIs, detached workers, visual
generation, package publication, browser validation, REST/WebSocket live use,
and deployment. Those operational layers are intentionally absent here.
"""


PUBLICATION_CHECKLIST = """# Publication Checklist

## Completed

- [x] Sanitized source snapshot with generated/runtime caches removed
- [x] Credential-pattern and private-path scan
- [x] File-level SHA-256 manifest
- [x] Reproducible archive checksum
- [x] Clean-install test suites for both archive boundaries
- [x] Final paper PDF and self-contained TeX figure bundle
- [x] Machine-readable evidence summary
- [x] Full-stack and lean-core boundaries documented

## Required Before Public OA Upload

- [ ] Replace `Anonymous Authors` in `paper/main.tex` with final author names,
      affiliations, and contact information.
- [ ] Choose and add the project software license. No license was inherited
      from the source repositories, so this archive does not guess one.
- [ ] Complete `CITATION.cff.example` and rename it to `CITATION.cff`.
- [ ] Add the final repository URL and DOI/arXiv identifier after allocation.

The paper is technically uploadable: it compiles, has embedded fonts, resolved
references, and no layout errors. The author and legal metadata above are the
remaining public-release blockers.
"""


VALIDATION_REPORT = """# Validation Report

Validation was run against clean generated snapshots on 2026-07-30.

| Artifact | Check | Result |
|---|---|---:|
| Agora-2.0 | Clean-install pytest suite | 146 passed |
| Agora-C | Deployment-independent core pytest suite | 4 passed |
| Paper | Two-pass XeLaTeX build from bundled source | 9 pages, passed |
| Paper | Unresolved citations, references, or overfull boxes | 0 |
| Archives | Credential-like values and private absolute paths | 0 findings |
| Archives | SHA-256 verification | passed |

The test suites do not require provider credentials or FLUX model weights.
Warnings are limited to upstream deprecations in FastAPI/Pillow and underfull
TeX boxes; they do not change runtime behavior or paper layout.
"""


LICENSE_REQUIRED = """# License Selection Required

The source repositories did not contain a project license. Copyright and
redistribution terms cannot be inferred safely.

Before public release, the copyright holder must choose a license and replace
this file with the corresponding `LICENSE` text. This archive intentionally
does not make that legal choice on the author's behalf.
"""


THIRD_PARTY_NOTICES = """# Third-Party Notices

- Phaser 3.90.0 is bundled in the full-stack archive and is distributed under
  the MIT License. See https://github.com/phaserjs/phaser.
- Google Gemini/Vertex services and model outputs are external services; no
  credentials or model weights are bundled.
- FLUX model weights are not bundled. Users must obtain them separately and
  comply with the license of the selected FLUX checkpoint.
- Python dependencies retain their respective upstream licenses.

This notice does not replace the required project-level license selection.
"""


CITATION_EXAMPLE = """cff-version: 1.2.0
message: "If you use Agora, please cite the accompanying paper."
title: "Agora"
type: software
version: "2026.07.30"
date-released: "2026-07-30"
authors:
  - family-names: "REPLACE_WITH_FAMILY_NAME"
    given-names: "REPLACE_WITH_GIVEN_NAME"
preferred-citation:
  type: article
  title: "Agora: One Sentence, One Executable World"
  authors:
    - family-names: "REPLACE_WITH_FAMILY_NAME"
      given-names: "REPLACE_WITH_GIVEN_NAME"
  year: 2026
"""


ENV_EXAMPLE = """# Structured generation
AGORA_AISTUDIO_API_KEY=
AGORA_VERTEX_API_KEY=

# Optional runtime overrides
AGORA_RUNTIME_PYTHON=
AGORA_FLUX_ENDPOINT=http://127.0.0.1:8135
AGORA_VERTEX_TELEMETRY_PATH=
"""


FULL_RELEASE_NOTES = f"""# Agora Full-Stack Snapshot

- Release date: {RELEASE_DATE}
- Archive role: runnable integration stack
- Paper: `Agora: One Sentence, One Executable World`
- Evaluated model route: AI Studio structured generation
- Evaluated raster route: FLUX HTTP service
- Runtime evidence: twenty ten-user sweeps
- Clean-install validation: 146 tests passed

This snapshot is built from the current working implementation rather than a
stale Git carrier. Runtime outputs, generated caches, local service units,
credentials, old report drafts, and internal maintenance memory are excluded.
"""


CORE_RELEASE_NOTES = f"""# Agora-C Snapshot

- Release date: {RELEASE_DATE}
- Archive role: lean compiler/runtime contracts
- Source of truth: synchronized from the current Agora full-stack core
- Clean-install validation: 4 tests passed

This snapshot supersedes the earlier heavyweight Agora-C working directory.
It intentionally contains no UI, deployment, browser harness, generated media,
or operational art pipeline.
"""


PAPER_README = """# Agora Paper Artifact

Contents:

- `main.pdf`: compiled OA/preprint candidate
- `main.tex`: self-contained source entry point
- `figures/`: vector figures used by the paper
- `evidence/`: compact machine-readable aggregate and supporting summaries

Compile from this directory with:

```bash
xelatex -interaction=nonstopmode -halt-on-error main.tex
xelatex -interaction=nonstopmode -halt-on-error main.tex
```

Before public upload, replace `Anonymous Authors` in `main.tex`. The PDF is
otherwise compiled with embedded fonts and resolved references.
"""


FULL_GITIGNORE = """# Local environments and credentials
.env
.env.*
!.env.example
.venv/

# Python and JavaScript build state
__pycache__/
*.py[cod]
.pytest_cache/
node_modules/

# Generated world/runtime state
output/
export_artifact/
scratch/
frontend/assets/generated/
frontend/assets/runtime_state/
macro_ui/generated/
*.log
*.db
*.sqlite*

# TeX auxiliaries
*.aux
*.out
*.toc
"""


CORE_GITIGNORE = """__pycache__/
*.py[cod]
.pytest_cache/
.venv/
.env
*.log
*.tmp
"""


CORE_REQUIREMENTS = """pydantic>=2.0
requests>=2.28.0
"""


DEV_REQUIREMENTS = """pytest>=8.0
"""


CORE_PYPROJECT = """[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "agora-c"
version = "2026.7.30"
description = "Lean compiler and runtime contracts for Agora"
requires-python = ">=3.10"
dependencies = [
  "pydantic>=2.0",
  "requests>=2.28.0",
]

[tool.setuptools.packages.find]
include = ["agora_ui*"]
"""


CORE_TEST_DEFAULTS = """from agora_ui.runtime.defaults import (
    DEFAULT_ORCHESTRATION,
    compile_orchestration_config,
)


def test_missing_orchestration_compiles_default_plan() -> None:
    compiled = compile_orchestration_config({"scenario_meta": {"world_id": "demo"}})
    assert compiled["mode"] == "json_declared_runtime"
    assert compiled["phases"][0]["phase_id"] == DEFAULT_ORCHESTRATION["phases"][0]["phase_id"]


def test_explicit_orchestration_overrides_defaults() -> None:
    compiled = compile_orchestration_config(
        {
            "orchestration": {
                "version": "custom_v1",
                "components": [{"component_id": "trace", "kind": "phase_trace"}],
                "policies": {"activation_policy": {"policy_id": "custom_activation"}},
                "phases": [
                    {
                        "phase_id": "only_phase",
                        "steps": [{"operation": "initialize_runtime"}],
                    }
                ],
            }
        }
    )
    assert compiled["version"] == "custom_v1"
    assert compiled["phases"][0]["phase_id"] == "only_phase"
"""


CORE_TEST_ENGINE = """from pathlib import Path

from agora_ui.runtime.engine import BaseComponent, RuntimeEngine, RuntimeExecutionContext


def test_nested_for_each_execution_is_json_driven() -> None:
    execution = []

    def seed(ctx: RuntimeExecutionContext, node: dict) -> None:
        ctx.set("rounds", [1, 2])
        ctx.set("actors", ["a", "b"])

    def record(ctx: RuntimeExecutionContext, node: dict) -> None:
        execution.append((ctx.get("round"), ctx.get("actor")))

    engine = RuntimeEngine(
        operation_registry={"seed": seed, "record": record},
        component_registry={
            "base": lambda component_id, spec: BaseComponent(
                component_id=component_id,
                config=spec,
            )
        },
    )
    plan = {
        "components": [{"component_id": "base_component", "kind": "base"}],
        "phases": [
            {"phase_id": "bootstrap", "steps": [{"operation": "seed"}]},
            {
                "phase_id": "loop",
                "for_each": "rounds",
                "item_as": "round",
                "steps": [
                    {
                        "phase_id": "actor_loop",
                        "for_each": "actors",
                        "item_as": "actor",
                        "steps": [{"operation": "record"}],
                    }
                ],
            },
        ],
    }
    context = RuntimeExecutionContext(
        args=None,
        config_path=Path("world.json"),
        config={},
        plan=plan,
    )
    engine.execute(context)
    assert execution == [(1, "a"), (1, "b"), (2, "a"), (2, "b")]
"""


CORE_TEST_PACKAGE = """from pathlib import Path

from agora_ui.package_db import materialize_world_package, read_world_package_metadata


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "examples" / "reference_world" / "world_package.db"


def test_reference_package_is_portable(tmp_path: Path) -> None:
    metadata = read_world_package_metadata(PACKAGE)
    assert metadata["package_kind"] == "agora_world_package"
    materialized = materialize_world_package(PACKAGE, output_dir=tmp_path / "world")
    assert materialized.config_path.is_file()
    assert materialized.scenario_dir.is_dir()
"""


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _common_allowed(path: Path) -> bool:
    if any(part in COMMON_REJECTED_PARTS for part in path.parts):
        return False
    if path.suffix.lower() in COMMON_REJECTED_SUFFIXES:
        return False
    return True


def _copy_tree(
    source: Path,
    target: Path,
    *,
    include: Callable[[Path], bool] | None = None,
) -> None:
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if not _common_allowed(relative):
            continue
        if include is not None and not include(relative):
            continue
        if path.is_dir():
            continue
        _copy_file(path, target / relative)


def _full_agora_include(relative: Path) -> bool:
    return relative.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}


def _full_frontend_include(relative: Path) -> bool:
    if relative.parts and relative.parts[0] == "assets":
        return False
    if relative.name in {
        "WorldScene.js.bak",
        "check_remaining.js",
        "method_list.txt",
        "reduce_worldscene.js",
        "split_live.js",
        "split_scene.js",
        "split_script.js",
    }:
        return False
    return True


def _full_macro_include(relative: Path) -> bool:
    if relative.parts and relative.parts[0] == "generated":
        return False
    if relative.name.startswith("split_"):
        return False
    return True


def _copy_paper(source_root: Path, target_root: Path) -> None:
    paper_root = target_root / "paper"
    source_tex = (
        source_root / "docs" / "agora_one_sentence_executable_world_paper_20260729.tex"
    )
    tex = source_tex.read_text(encoding="utf-8").replace(
        "docs/figures_20260729/",
        "figures/",
    )
    _write_text(paper_root / "main.tex", tex)
    _copy_file(
        source_root
        / "docs"
        / "agora_one_sentence_executable_world_paper_20260729.pdf",
        paper_root / "main.pdf",
    )
    for name in (
        "five_world_strip.pdf",
        "objective_results.pdf",
        "one_sentence_pipeline.pdf",
    ):
        _copy_file(
            source_root / "docs" / "figures_20260729" / name,
            paper_root / "figures" / name,
        )
    for name in (
        "paper_evidence_summary_20260729.json",
        "paper_evidence_summary_20260729.md",
        "paper_cost_analysis_20260729.json",
        "seeded_fault_benchmark_20260729.json",
        "runtime_evaluation_summary.json",
        "headless_message_latency_summary.json",
    ):
        _copy_file(
            source_root / "docs" / "benchmark_20260724" / name,
            paper_root / "evidence" / name,
        )
    _write_text(paper_root / "README.md", PAPER_README)


def _copy_evidence(source_root: Path, target_root: Path) -> None:
    source = source_root / "docs" / "benchmark_20260724"
    target = target_root / "docs" / "benchmark_20260724"
    for relative_name in sorted(EVIDENCE_FILES | EVIDENCE_NESTED_FILES):
        _copy_file(source / relative_name, target / relative_name)


def _sanitize_reference_db(path: Path, *, source_label: str) -> None:
    if not path.is_file():
        return
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE meta SET value = ? WHERE key = 'source_root'",
            (source_label,),
        )
        conn.execute(
            "DELETE FROM files WHERE path LIKE 'projections/%' OR path = 'flux_asset_job_example.json'"
        )
        rows = conn.execute("SELECT path, content FROM files").fetchall()
        for relative_path, raw_content in rows:
            if not str(relative_path).endswith(".json"):
                continue
            try:
                payload = json.loads(bytes(raw_content).decode("utf-8"))
            except Exception:
                continue
            sanitized = _sanitize_json_payload(payload)
            encoded = json.dumps(
                sanitized,
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            conn.execute(
                "UPDATE files SET size = ?, sha256 = ?, content = ? WHERE path = ?",
                (
                    len(encoded),
                    hashlib.sha256(encoded).hexdigest(),
                    encoded,
                    str(relative_path),
                ),
            )
        conn.commit()


def _sanitize_json_payload(payload: object, *, key: str = "") -> object:
    local_only_keys = {
        "artifact_dir",
        "command_log_path",
        "config_path",
        "default_output_dir",
        "image_path",
        "longlive_root",
        "prompts_jsonl_path",
        "template_config",
        "vertex_cred_file",
        "video_path",
    }
    if isinstance(payload, dict):
        return {
            str(child_key): _sanitize_json_payload(
                child_value,
                key=str(child_key),
            )
            for child_key, child_value in payload.items()
        }
    if isinstance(payload, list):
        return [_sanitize_json_payload(item, key=key) for item in payload]
    if (
        isinstance(payload, str)
        and key in local_only_keys
        and payload.startswith("/home/")
    ):
        return ""
    return payload


def _sanitize_json_files(root: Path) -> None:
    for path in sorted(root.rglob("*.json")):
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        sanitized = _sanitize_json_payload(payload)
        if sanitized != payload:
            path.write_text(
                json.dumps(sanitized, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )


def _sanitize_text_tree(root: Path, source_root: Path) -> None:
    replacements = {
        str(source_root): ".",
        "/home/yz_wang/yz_main/Agora_UI_Run": ".",
        "/home/yz_wang/.conda/envs/new_py310/bin/python3.10": "python",
        "/home/yz_wang/.conda/envs/new_py310/bin/python": "python",
        "/home/yz_wang": "${HOME}",
    }
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        sanitized = text
        for old, new in replacements.items():
            sanitized = sanitized.replace(old, new)
        if sanitized != text:
            path.write_text(sanitized, encoding="utf-8")


def _write_common_release_files(target: Path, *, release_notes: str) -> None:
    _write_text(target / "PUBLICATION_CHECKLIST.md", PUBLICATION_CHECKLIST)
    _write_text(target / "VALIDATION_REPORT.md", VALIDATION_REPORT)
    _write_text(target / "LICENSE_REQUIRED.md", LICENSE_REQUIRED)
    _write_text(target / "THIRD_PARTY_NOTICES.md", THIRD_PARTY_NOTICES)
    _write_text(target / "CITATION.cff.example", CITATION_EXAMPLE)
    _write_text(target / "RELEASE_NOTES.md", release_notes)
    _write_text(target / "requirements-dev.txt", DEV_REQUIREMENTS)


def _build_full(source_root: Path, target: Path) -> None:
    _write_text(target / "README.md", FULL_README)
    _write_text(target / ".gitignore", FULL_GITIGNORE)
    _write_text(target / ".env.example", ENV_EXAMPLE)
    _copy_file(source_root / "requirements.txt", target / "requirements.txt")
    if (source_root / "pytest.ini").is_file():
        _copy_file(source_root / "pytest.ini", target / "pytest.ini")
    _copy_file(source_root / "ARCHITECTURE.md", target / "ARCHITECTURE.md")
    _copy_file(
        source_root / "SYNC_WITH_AGORA_C.md",
        target / "SYNC_WITH_AGORA_C.md",
    )
    for name in ("launch_interaction_new_py310.sh", "launch_macro_ui_new_py310.sh"):
        _copy_file(source_root / name, target / name)

    _copy_tree(
        source_root / "agora_ui",
        target / "agora_ui",
        include=_full_agora_include,
    )
    _copy_tree(
        source_root / "asset_pipeline",
        target / "asset_pipeline",
        include=_full_agora_include,
    )
    _copy_tree(
        source_root / "frontend",
        target / "frontend",
        include=_full_frontend_include,
    )
    _copy_tree(
        source_root / "macro_ui",
        target / "macro_ui",
        include=_full_macro_include,
    )
    _copy_tree(source_root / "world_creator_ui", target / "world_creator_ui")
    _copy_tree(source_root / "tests", target / "tests")
    _copy_tree(
        source_root / "sample_json",
        target / "sample_json",
        include=lambda relative: not (
            relative.parts and relative.parts[0] == "projections"
        ),
    )

    for name in sorted(FULL_SCRIPT_ALLOWLIST):
        source = source_root / "scripts" / name
        if source.is_file():
            _copy_file(source, target / "scripts" / name)

    _copy_evidence(source_root, target)
    _copy_paper(source_root, target)
    _write_text(
        target / "deploy" / "README.md",
        """# Deployment Templates

Private systemd units, Cloudflare credentials, tokens, and downloaded binaries
are not included. Configure deployment paths for the target host and load
credentials from environment files outside the repository.
""",
    )
    _write_common_release_files(target, release_notes=FULL_RELEASE_NOTES)
    _sanitize_reference_db(
        target / "sample_json" / "world_package.db",
        source_label="sample_json",
    )


def _build_core(source_root: Path, target: Path) -> None:
    _write_text(target / "README.md", CORE_README)
    _write_text(target / "ARCHITECTURE.md", CORE_ARCHITECTURE)
    _write_text(target / ".gitignore", CORE_GITIGNORE)
    _write_text(target / "requirements.txt", CORE_REQUIREMENTS)
    _write_text(target / "pyproject.toml", CORE_PYPROJECT)
    _write_common_release_files(target, release_notes=CORE_RELEASE_NOTES)

    for name in sorted(CORE_MODULE_FILES):
        _copy_file(
            source_root / "agora_ui" / name,
            target / "agora_ui" / name,
        )
    for tree_name in ("data/registries", "runtime", "universal_adjudicator"):
        _copy_tree(
            source_root / "agora_ui" / tree_name,
            target / "agora_ui" / tree_name,
        )

    _copy_tree(
        source_root / "sample_json",
        target / "examples" / "reference_world",
        include=lambda relative: not (
            relative.parts and relative.parts[0] == "projections"
        ),
    )
    _sanitize_reference_db(
        target / "examples" / "reference_world" / "world_package.db",
        source_label="examples/reference_world",
    )
    _write_text(
        target / "tests" / "test_runtime_defaults.py",
        CORE_TEST_DEFAULTS,
    )
    _write_text(
        target / "tests" / "test_runtime_engine.py",
        CORE_TEST_ENGINE,
    )
    _write_text(
        target / "tests" / "test_reference_package.py",
        CORE_TEST_PACKAGE,
    )
    _copy_paper(source_root, target)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_manifest(root: Path) -> dict[str, object]:
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "FILE_MANIFEST.json":
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    payload: dict[str, object] = {
        "archive": root.name,
        "release_date": RELEASE_DATE,
        "file_count": len(files),
        "total_bytes": sum(int(item["size_bytes"]) for item in files),
        "files": files,
    }
    _write_text(
        root / "FILE_MANIFEST.json",
        json.dumps(payload, indent=2, ensure_ascii=True),
    )
    return payload


def _validate_tree(root: Path) -> dict[str, object]:
    issues: list[str] = []
    forbidden_names = {
        "README For LLM.md",
        "MemoryFrontEnd.md",
        "session_memory.md",
        "publish_output.json",
        "vertex_error_raw_text_dump.txt",
    }
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if path.name in forbidden_names:
            issues.append(f"internal file included: {relative}")
        if any(part in COMMON_REJECTED_PARTS for part in relative.parts):
            issues.append(f"cache directory included: {relative}")
        if path.suffix.lower() in COMMON_REJECTED_SUFFIXES:
            issues.append(f"temporary file included: {relative}")
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "/home/yz_wang" in text or "Agora_UI_Run" in text:
            issues.append(f"private absolute path included: {relative}")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                issues.append(f"credential-like value included: {relative}")
                break
    if issues:
        raise RuntimeError(
            f"Publication validation failed for {root}:\n- "
            + "\n- ".join(issues[:100])
        )
    return {"status": "ok", "issues": []}


def _archive_directory(source: Path, output_path: Path) -> None:
    with tarfile.open(output_path, "w:gz", compresslevel=9) as archive:
        archive.add(source, arcname=source.name)


def _write_archive_checksums(paths: Iterable[Path], output_path: Path) -> None:
    lines = [f"{_sha256(path)}  {path.name}" for path in paths]
    _write_text(output_path, "\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "publish_ready"
        / f"Agora_{RELEASE_ID}",
    )
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    output_root = args.output_root.resolve()

    if output_root == source_root or source_root in output_root.parents:
        raise ValueError("Output root must be outside the source repository.")
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    full_root = output_root / "Agora-2.0"
    core_root = output_root / "Agora-C"
    _build_full(source_root, full_root)
    _build_core(source_root, core_root)
    _sanitize_json_files(full_root)
    _sanitize_json_files(core_root)
    _sanitize_text_tree(full_root, source_root)
    _sanitize_text_tree(core_root, source_root)

    validation = {
        "Agora-2.0": _validate_tree(full_root),
        "Agora-C": _validate_tree(core_root),
    }
    manifests = {
        "Agora-2.0": _write_manifest(full_root),
        "Agora-C": _write_manifest(core_root),
    }

    full_archive = output_root / f"Agora-2.0-publish-ready-{RELEASE_ID}.tar.gz"
    core_archive = output_root / f"Agora-C-publish-ready-{RELEASE_ID}.tar.gz"
    _archive_directory(full_root, full_archive)
    _archive_directory(core_root, core_archive)
    _write_archive_checksums(
        (full_archive, core_archive),
        output_root / "SHA256SUMS",
    )
    _write_text(
        output_root / "RELEASE_INDEX.json",
        json.dumps(
            {
                "release_date": RELEASE_DATE,
                "validation": validation,
                "manifests": {
                    name: {
                        "file_count": payload["file_count"],
                        "total_bytes": payload["total_bytes"],
                    }
                    for name, payload in manifests.items()
                },
                "archives": [full_archive.name, core_archive.name],
                "oa_blockers": [
                    "replace Anonymous Authors",
                    "choose project software license",
                    "complete citation metadata",
                ],
            },
            indent=2,
            ensure_ascii=True,
        ),
    )
    print(
        json.dumps(
            {
                "output_root": str(output_root),
                "full_archive": str(full_archive),
                "core_archive": str(core_archive),
                "validation": validation,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
