#!/usr/bin/env python3
"""Build a TeX/PDF story report for a JSON-defined interaction run."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .boundary_schemas import ImageJobSpec, RunConfigSpec, StoryPayloadSpec, VideoJobSpec
from .jsonc_utils import load_jsonc_path


SCRIPT_DIR = Path(__file__).resolve().parent.parent


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not a JSON object")
    return payload


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return _read_json(path)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split()).strip()


def _escape_tex(text: Any) -> str:
    mapping = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(mapping.get(ch, ch) for ch in str(text))


def _sentence(story: dict[str, Any]) -> str:
    actor = _clean(story.get("actor_name") or story.get("actor_id"))
    target = _clean(story.get("target_name") or story.get("target_id"))
    verb = _clean(story.get("story_verb") or story.get("kind") or "interacted with")
    room = _clean(story.get("actor_room_id") or "world")
    detail = ""
    if story.get("kind") == "item_trade":
        detail = " as part of the supply economy"
    elif story.get("kind") == "cinematic":
        status = _clean(story.get("longlive_status"))
        detail = f" in a cinematic body-cooperation action ({status})" if status else " in a cinematic body-cooperation action"
    elif story.get("kind") == "image":
        status = _clean(story.get("image_status"))
        detail = f" in a still-image artifact action ({status})" if status else " in a still-image artifact action"
    return f"{actor} {verb} {target} in {room}{detail}."


def _round_story(stories: list[dict[str, Any]]) -> str:
    if not stories:
        return "No activated interaction was recorded in this round."
    sentences = [_sentence(item) for item in stories[:8]]
    if len(stories) > 8:
        sentences.append(f"{len(stories) - 8} additional interactions continued in the background.")
    return " ".join(sentences)


def _route_table(route_counts: dict[str, Any]) -> list[str]:
    rows = []
    for key, raw in sorted(route_counts.items(), key=lambda item: (-int(item[1]), item[0])):
        rows.append(rf"{_escape_tex(key)} & {int(raw)} \\")
    return rows


def _video_examples(video_jobs: list[dict[str, Any]], limit: int = 5) -> list[str]:
    lines: list[str] = []
    for job in video_jobs[:limit]:
        actor = _clean(job.get("actor_id"))
        target = _clean(job.get("target_id"))
        status = _clean(job.get("status"))
        prompt = _clean(job.get("actor_prompt"))
        continuation = _clean(job.get("target_continuation_prompt"))
        video_path = _clean(job.get("video_path"))
        config_path = _clean(job.get("config_path"))
        lines.append(
            rf"\item \textbf{{{_escape_tex(actor)} -> {_escape_tex(target)}}} "
            rf"status={_escape_tex(status)}\\"
            rf"\newline Actor prompt: {_escape_tex(prompt)}\\"
            rf"\newline Target continuation: {_escape_tex(continuation)}\\"
            rf"\newline Config: \url{{{_escape_tex(config_path)}}}\\"
            rf"\newline Video: \url{{{_escape_tex(video_path)}}}"
        )
    if not lines:
        lines.append(r"\item No LongLive jobs were recorded.")
    return lines


def _image_examples(image_jobs: list[dict[str, Any]], limit: int = 8) -> list[str]:
    lines: list[str] = []
    for job in image_jobs[:limit]:
        actor = _clean(job.get("actor_id"))
        target = _clean(job.get("target_id"))
        status = _clean(job.get("status"))
        prompt = _clean(job.get("prompt"))
        image_path = _clean(job.get("image_path"))
        lines.append(
            rf"\item \textbf{{{_escape_tex(actor)} -> {_escape_tex(target)}}} "
            rf"status={_escape_tex(status)}\\"
            rf"\newline Prompt: {_escape_tex(prompt)}\\"
            rf"\newline Image: \url{{{_escape_tex(image_path)}}}"
        )
    if not lines:
        lines.append(r"\item No still-image artifact jobs were recorded.")
    return lines


def _api_round_lines(api_summary: dict[str, Any]) -> list[str]:
    rows: list[str] = []
    for item in api_summary.get("round_summaries", []) or []:
        if not isinstance(item, dict):
            continue
        round_index = int(item.get("round_index", 0))
        summary = _clean(item.get("story_summary"))
        task = _clean(item.get("key_trade_or_task"))
        representative = _clean(item.get("representative_interaction"))
        rows.append(rf"\subsection{{API Round {round_index}}}")
        rows.append(_escape_tex(summary))
        if task:
            rows.append(rf"\newline \textbf{{Trade or task thread}}: {_escape_tex(task)}")
        if representative:
            rows.append(rf"\newline \textbf{{Representative interaction}}: {_escape_tex(representative)}")
        rows.append("")
    return rows


def _build_tex(
    run_dir: Path,
    config: dict[str, Any],
    story: dict[str, Any],
    video_jobs: list[dict[str, Any]],
    image_jobs: list[dict[str, Any]],
    api_summary: dict[str, Any],
) -> str:
    report_config = config.get("report", {})
    title = _clean(report_config.get("title") or f"{config.get('scenario_meta', {}).get('world_name', 'Simulation')} Story Summary")
    author = _clean(report_config.get("author") or "Agora Mini Interaction Runner")
    story_filename = _clean(config.get("output", {}).get("story_filename") or "story.json")
    meta = config.get("scenario_meta", {})
    round_summaries = story.get("round_summaries", [])
    stories = story.get("stories", [])
    stories_by_round: dict[int, list[dict[str, Any]]] = {}
    for item in stories:
        stories_by_round.setdefault(int(item.get("round_index", 0)), []).append(item)
    route_counts = story.get("route_counts", {})
    longlive_counts = story.get("longlive_counts", {})
    image_counts = story.get("image_counts", {})
    legality = story.get("target_legality", {})

    lines = [
        r"\documentclass[11pt,a4paper]{article}",
        r"\usepackage[margin=1.8cm]{geometry}",
        r"\usepackage[hidelinks]{hyperref}",
        r"\usepackage{longtable}",
        r"\title{" + _escape_tex(title) + "}",
        r"\author{" + _escape_tex(author) + "}",
        r"\date{\today}",
        r"\begin{document}",
        r"\maketitle",
        r"\tableofcontents",
        "",
        r"\section{Run Overview}",
        rf"\textbf{{Run Dir}}: \url{{{_escape_tex(str(run_dir))}}}\\",
        rf"\textbf{{World}}: {_escape_tex(meta.get('world_name', ''))}\\",
        rf"\textbf{{Objective}}: {_escape_tex(meta.get('simulation_objective', ''))}\\",
        rf"\textbf{{Target Legality Failures}}: {int(legality.get('invalid_count', 0))}\\",
        "",
        r"\section{Route Mix}",
        r"\begin{longtable}{lr}",
        r"\textbf{Route} & \textbf{Count}\\",
        *(_route_table(route_counts) or [r"none & 0 \\"]),
        r"\end{longtable}",
        "",
        r"\section{LongLive Status}",
        r"\begin{longtable}{lr}",
        r"\textbf{Status} & \textbf{Count}\\",
        *(_route_table(longlive_counts) or [r"none & 0 \\"]),
        r"\end{longtable}",
        "",
        r"\section{Image Artifact Status}",
        r"\begin{longtable}{lr}",
        r"\textbf{Status} & \textbf{Count}\\",
        *(_route_table(image_counts) or [r"none & 0 \\"]),
        r"\end{longtable}",
        "",
        r"\section{API Story Summary}",
        _escape_tex(api_summary.get("overall_story_summary", "No API story summary was generated.")),
        "",
        r"\subsection{Quest and Trade}",
        _escape_tex(api_summary.get("quest_and_trade_summary", "No API quest or trade summary was generated.")),
        "",
        r"\subsection{Video Prompt Chain}",
        _escape_tex(api_summary.get("video_prompt_chain_summary", "No API video prompt chain summary was generated.")),
        "",
        r"\subsection{Image Artifacts}",
        _escape_tex(api_summary.get("image_artifact_summary", "No API image artifact summary was generated.")),
        "",
        r"\section{Round-by-Round Story}",
        *(_api_round_lines(api_summary) or []),
    ]

    for summary in round_summaries:
        round_index = int(summary.get("round_index", 0))
        lines.append(rf"\subsection{{Round {round_index}}}")
        lines.append(
            rf"Activated agents: {int(summary.get('activated_agent_count', 0))}; "
            rf"intents: {int(summary.get('intent_count', 0))}; "
            rf"video jobs: {int(summary.get('video_job_count', 0))}; "
            rf"image jobs: {int(summary.get('image_job_count', 0))}; "
            rf"action successes: {int(summary.get('action_success_count', 0))}."
        )
        lines.append("")
        lines.append(_escape_tex(_round_story(stories_by_round.get(round_index, []))))
        lines.append("")

    lines.extend(
        [
            r"\section{Representative Video Prompts}",
            r"\begin{enumerate}",
            *_video_examples(video_jobs),
            r"\end{enumerate}",
            "",
            r"\section{Representative Image Artifacts}",
            r"\begin{enumerate}",
            *_image_examples(image_jobs),
            r"\end{enumerate}",
            "",
            r"\section{Artifacts}",
            rf"Story JSON: \url{{{_escape_tex(str(run_dir / story_filename))}}}\\",
            rf"Timeline JSONL: \url{{{_escape_tex(str(run_dir / 'timeline.jsonl'))}}}\\",
            rf"Video Jobs JSONL: \url{{{_escape_tex(str(run_dir / 'video_prompt_jobs.jsonl'))}}}\\",
            rf"Image Jobs JSONL: \url{{{_escape_tex(str(run_dir / 'image_jobs.jsonl'))}}}\\",
            r"\end{document}",
            "",
        ]
    )
    return "\n".join(lines)


def _build_pdf(tex_path: Path, pdf_path: Path) -> bool:
    xelatex = shutil.which("xelatex")
    if xelatex is None:
        raise RuntimeError("xelatex is required to build PDF reports")
    cmd = [
        xelatex,
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        "-output-directory",
        str(tex_path.parent),
        tex_path.name,
    ]
    for _ in range(2):
        result = subprocess.run(cmd, cwd=tex_path.parent, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                "xelatex failed:\n"
                + "\n".join((result.stdout or "").splitlines()[-60:])
                + "\n"
                + "\n".join((result.stderr or "").splitlines()[-60:])
            )
    generated = tex_path.with_suffix(".pdf")
    if generated.is_file() and generated != pdf_path:
        pdf_path.write_bytes(generated.read_bytes())
    return pdf_path.is_file()


def build_report(*, run_dir: Path, config: dict[str, Any] | None = None) -> dict[str, str]:
    run_dir = run_dir.expanduser().resolve()
    if config is None:
        run_config = _read_json(run_dir / "run_config.json")
        config = load_jsonc_path(run_config["config_path"])
    run_config = _read_optional_json(run_dir / "run_config.json")
    if run_config:
        run_config = RunConfigSpec.model_validate(run_config).model_dump()
    story_filename = _clean(run_config.get("story_filename") or config.get("output", {}).get("story_filename") or "story.json")
    story = StoryPayloadSpec.model_validate(_read_json(run_dir / story_filename)).model_dump()
    video_jobs = [VideoJobSpec.model_validate(row).model_dump() for row in _read_jsonl(run_dir / "video_prompt_jobs.jsonl")]
    image_jobs = [ImageJobSpec.model_validate(row).model_dump() for row in _read_jsonl(run_dir / "image_jobs.jsonl")]
    api_summary = _read_optional_json(run_dir / "api_story_summary.json")
    report_dir = run_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_config = config.get("report", {})
    tex_name = _clean(report_config.get("tex_filename") or "story_report.tex")
    pdf_name = _clean(report_config.get("pdf_filename") or str(Path(tex_name).with_suffix(".pdf")))
    tex_path = report_dir / tex_name
    pdf_path = report_dir / pdf_name
    tex_path.write_text(_build_tex(run_dir, config, story, video_jobs, image_jobs, api_summary), encoding="utf-8")
    _build_pdf(tex_path, pdf_path)
    return {"report_tex": str(tex_path), "report_pdf": str(pdf_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a JSON-defined interaction story report.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()
    config = load_jsonc_path(args.config) if args.config is not None else None
    info = build_report(run_dir=args.run_dir, config=config)
    print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
