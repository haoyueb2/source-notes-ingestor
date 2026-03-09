from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import DerivedScopeManifest
from .scope_loader import derived_scope_dir, load_scope, project_root, resolve_scope_source_path
from .utils import ensure_dir


class CodexUnavailableError(RuntimeError):
    pass


@dataclass(slots=True)
class VaultNoteRecord:
    path: Path
    relpath: str
    source: str
    author_name: str
    content_type: str
    title: str
    summary: str
    published_at: str | None
    updated_at: str | None
    body: str


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text

    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return {}, text

    metadata: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        metadata[key.strip()] = value.strip().strip('"')
    return metadata, parts[2]


def _load_scope_notes(scope_id: str, vault_path: str | Path, scopes_dir: str | Path | None = None) -> tuple[object, list[VaultNoteRecord]]:
    scope = load_scope(scope_id, scopes_dir=scopes_dir)
    vault_root = Path(vault_path).expanduser()
    notes: list[VaultNoteRecord] = []
    for source in scope.sources:
        root = resolve_scope_source_path(source, vault_root)
        if not root.exists():
            continue
        for note_path in sorted(root.rglob("*.md")):
            text = note_path.read_text(encoding="utf-8")
            metadata, body = _parse_frontmatter(text)
            relpath = str(note_path.relative_to(vault_root))
            notes.append(
                VaultNoteRecord(
                    path=note_path,
                    relpath=relpath,
                    source=metadata.get("source") or source.source or "unknown",
                    author_name=metadata.get("author_name") or source.author_name or source.account_name or scope.display_name,
                    content_type=metadata.get("content_type") or "note",
                    title=metadata.get("title") or note_path.stem,
                    summary=metadata.get("summary") or "",
                    published_at=metadata.get("published_at"),
                    updated_at=metadata.get("updated_at"),
                    body=body.strip(),
                )
            )
    notes.sort(key=lambda item: (item.source, item.content_type, item.relpath))
    return scope, notes


def _yaml_scalar(value: str | None) -> str:
    return f'"{(value or "").replace(chr(34), chr(39))}"' if value is not None else "null"


def _yaml_list(values: list[str]) -> str:
    if not values:
        return "[]"
    lines = [""] + [f'  - "{value.replace(chr(34), chr(39))}"' for value in values]
    return "\n".join(lines)


def _derived_frontmatter(scope_id: str, kind: str, note_paths: list[str]) -> str:
    return "\n".join(
        [
            "---",
            'derived: "true"',
            f'scope_id: "{scope_id}"',
            f'derived_kind: "{kind}"',
            f"source_note_paths: {_yaml_list(note_paths)}",
            "---",
            "",
        ]
    )


def _write_derived_note(target: Path, scope_id: str, kind: str, body: str, note_paths: list[str]) -> Path:
    ensure_dir(target.parent)
    target.write_text(_derived_frontmatter(scope_id, kind, note_paths) + body.rstrip() + "\n", encoding="utf-8")
    return target


def _build_manifest_body(scope, notes: list[VaultNoteRecord], generated_files: dict[str, str]) -> str:
    source_counts: dict[str, int] = {}
    content_counts: dict[str, int] = {}
    for note in notes:
        source_counts[note.source] = source_counts.get(note.source, 0) + 1
        content_counts[note.content_type] = content_counts.get(note.content_type, 0) + 1

    lines = [
        f"# Scope Manifest: {scope.display_name}",
        "",
        f"- Scope ID: `{scope.scope_id}`",
        f"- Source roots: {len(scope.sources)}",
        f"- Total notes: {len(notes)}",
        "",
        "## Source Counts",
    ]
    lines.extend([f"- `{name}`: {count}" for name, count in sorted(source_counts.items())])
    lines.extend(["", "## Content Type Counts"])
    lines.extend([f"- `{name}`: {count}" for name, count in sorted(content_counts.items())])
    lines.extend(["", "## Generated Files"])
    lines.extend([f"- `{kind}`: `{path}`" for kind, path in sorted(generated_files.items())])
    return "\n".join(lines)


def _build_corpus_index_body(scope, notes: list[VaultNoteRecord]) -> str:
    lines = [f"# Corpus Index: {scope.display_name}", ""]
    for idx, note in enumerate(notes, start=1):
        lines.extend(
            [
                f"## {idx:03d}. {note.title}",
                "",
                f"- Path: `{note.relpath}`",
                f"- Source: `{note.source}`",
                f"- Type: `{note.content_type}`",
                f"- Author: `{note.author_name}`",
                f"- Published: {_yaml_scalar(note.published_at)}",
                f"- Updated: {_yaml_scalar(note.updated_at)}",
                f"- Summary: {note.summary or '(none)'}",
                "",
            ]
        )
    return "\n".join(lines)


def _build_full_context_body(scope, notes: list[VaultNoteRecord]) -> str:
    lines = [
        f"# Full Context: {scope.display_name}",
        "",
        "This file is a rebuildable context pack. It is derived from raw vault notes and should not be treated as the final evidence layer.",
        "",
    ]
    for idx, note in enumerate(notes, start=1):
        lines.extend(
            [
                f"## Note {idx:03d}: {note.title}",
                "",
                f"- Path: `{note.relpath}`",
                f"- Source: `{note.source}`",
                f"- Type: `{note.content_type}`",
                f"- Summary: {note.summary or '(none)'}",
                "",
                note.body or "(empty)",
                "",
            ]
        )
    return "\n".join(lines)


def _codex_binary() -> str:
    binary = shutil.which("codex")
    if not binary:
        raise CodexUnavailableError("codex CLI was not found in PATH.")
    return binary


def _codex_exec_prefix(binary: str, cwd: Path, vault_path: Path) -> list[str]:
    cmd = [binary, "exec", "-C", str(cwd), "--add-dir", str(vault_path)]
    model = os.environ.get("OKI_CODEX_MODEL")
    if model:
        cmd.extend(["-m", model])
    reasoning = os.environ.get("OKI_CODEX_REASONING_EFFORT")
    if reasoning:
        cmd.extend(["-c", f'model_reasoning_effort="{reasoning}"'])
    return cmd


def _should_stream_codex_output() -> bool:
    raw = os.environ.get("OKI_CODEX_STREAM")
    if raw is None:
        return True
    return raw.lower() not in {"0", "false", "no"}


def _build_scope_map_prompt(scope_id: str, display_name: str, manifest_path: Path, corpus_index_path: Path, full_context_path: Path) -> str:
    return f"""
You are building a serious-study author map for the vault scope "{scope_id}" ({display_name}).

Read only these exact files from the vault:
- {manifest_path}
- {corpus_index_path}
- {full_context_path}

Use the exact paths above directly. Do not search the broader filesystem for alternative copies.

Return JSON only matching the provided schema.

General requirements:
- Write in Chinese.
- Do not invent facts outside the source files.
- Do not add YAML frontmatter.
- Treat all outputs as derived navigation aids, not final evidence.
- Optimize for depth, structure, and reuse by a serious long-form thinking workflow, not for brevity.

Requirements for overview_markdown:
- Produce a long-form author map, roughly 2500-4500 Chinese characters.
- Use this section structure exactly:
  - `# Author Overview: {display_name}`
  - `## Central Preoccupations`
  - `## Recurring Questions`
  - `## Thinking Method`
  - `## Human Nature, Intimacy, and Relationship`
  - `## Growth, Discipline, Freedom, and Work`
  - `## Time, Loneliness, Suffering, and Death`
  - `## Style, Tone, and Emotional Texture`
  - `## Tensions and Contradictions`
  - `## Cross-Source Continuity and Evolution`
  - `## Retrieval Guidance`
- Each section should contain dense prose, not bullets only.
- Inline-reference raw note paths with backticks throughout the document.
- Mention at least 12 distinct raw note paths across the whole overview.
- Make the overview feel like a serious intellectual orientation document, not a short summary.

Requirements for themes_markdown:
- Produce a rich theme atlas, roughly 3000-5000 Chinese characters.
- Start with `# Theme Atlas: {display_name}`.
- Then provide 12-18 theme sections using this exact pattern:
  - `## Theme NN: <theme name>`
  - `### Why It Matters`
  - `### Core Claims Or Intuitions`
  - `### Productive Retrieval Angles`
  - `### Tensions And Counterpoints`
  - `### Representative Note Paths`
- Each theme should be meaningfully distinct, not cosmetic renaming.
- Representative note paths must be raw note paths in backticks, ideally 3-6 per theme.
- Cover both Zhihu and WeChat materials where possible.
- Prefer narrower, retrieval-usable themes over a few oversized umbrella categories.
""".strip()


def _run_codex_json(prompt: str, schema: dict[str, object], cwd: Path, vault_path: Path) -> dict[str, str]:
    binary = _codex_binary()
    env = dict(os.environ)
    src_root = project_root() / "src"
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(src_root) if not existing_pythonpath else f"{src_root}:{existing_pythonpath}"
    stream_output = _should_stream_codex_output()
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_root = Path(tmp_dir)
        schema_path = tmp_root / "schema.json"
        output_path = tmp_root / "response.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
        result = subprocess.run(
            _codex_exec_prefix(binary, cwd=cwd, vault_path=vault_path)
            + [
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "-",
            ],
            cwd=cwd,
            env=env,
            input=prompt,
            capture_output=not stream_output,
            text=True,
        )
        if result.returncode != 0:
            message = ""
            if not stream_output:
                message = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(message or "codex exec failed while building QA summaries.")
        return json.loads(output_path.read_text(encoding="utf-8"))


def _generate_codex_derived_notes(scope_id: str, display_name: str, derived_dir: Path, note_paths: list[str], vault_path: Path) -> dict[str, str]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["overview_markdown", "themes_markdown"],
        "properties": {
            "overview_markdown": {"type": "string"},
            "themes_markdown": {"type": "string"},
        },
    }
    manifest_path = derived_dir / "manifest.md"
    corpus_index_path = derived_dir / "corpus_index.md"
    full_context_path = derived_dir / "full_context.md"
    prompt = _build_scope_map_prompt(scope_id, display_name, manifest_path, corpus_index_path, full_context_path)
    payload = _run_codex_json(prompt, schema=schema, cwd=project_root(), vault_path=vault_path)
    overview_path = _write_derived_note(derived_dir / "overview.md", scope_id, "overview", payload["overview_markdown"], note_paths)
    themes_path = _write_derived_note(derived_dir / "themes.md", scope_id, "themes", payload["themes_markdown"], note_paths)
    return {"overview": str(overview_path.relative_to(vault_path)), "themes": str(themes_path.relative_to(vault_path))}


def build_scope_package(
    scope_id: str,
    vault_path: str | Path,
    scopes_dir: str | Path | None = None,
    rebuild: bool = False,
) -> DerivedScopeManifest:
    vault_root = Path(vault_path).expanduser()
    scope, notes = _load_scope_notes(scope_id, vault_root, scopes_dir=scopes_dir)
    if not notes:
        raise RuntimeError(f"No notes found for scope {scope_id!r}.")

    derived_dir = derived_scope_dir(scope.scope_id, vault_root)
    if rebuild and derived_dir.exists():
        shutil.rmtree(derived_dir)
    ensure_dir(derived_dir)

    note_paths = [note.relpath for note in notes]
    generated_files: dict[str, str] = {}

    manifest_body = _build_manifest_body(scope, notes, generated_files={})
    generated_files["manifest"] = str(
        _write_derived_note(derived_dir / "manifest.md", scope.scope_id, "manifest", manifest_body, note_paths).relative_to(vault_root)
    )
    corpus_body = _build_corpus_index_body(scope, notes)
    generated_files["corpus_index"] = str(
        _write_derived_note(derived_dir / "corpus_index.md", scope.scope_id, "corpus_index", corpus_body, note_paths).relative_to(vault_root)
    )
    full_context_body = _build_full_context_body(scope, notes)
    generated_files["full_context"] = str(
        _write_derived_note(derived_dir / "full_context.md", scope.scope_id, "full_context", full_context_body, note_paths).relative_to(vault_root)
    )

    codex_files = _generate_codex_derived_notes(scope.scope_id, scope.display_name, derived_dir, note_paths, vault_root)
    generated_files.update(codex_files)

    manifest_body = _build_manifest_body(scope, notes, generated_files=generated_files)
    _write_derived_note(derived_dir / "manifest.md", scope.scope_id, "manifest", manifest_body, note_paths)

    source_counts: dict[str, int] = {}
    for note in notes:
        source_counts[note.source] = source_counts.get(note.source, 0) + 1
    return DerivedScopeManifest(
        scope_id=scope.scope_id,
        display_name=scope.display_name,
        derived_dir=str(derived_dir.relative_to(vault_root)),
        source_roots=[source.path for source in scope.sources],
        source_note_paths=note_paths,
        generated_files=generated_files,
        note_count=len(notes),
        source_counts=source_counts,
    )
