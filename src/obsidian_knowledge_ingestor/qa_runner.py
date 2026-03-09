from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from .models import AskResultBundle, EvidenceItem, QueryResult
from .scope_loader import default_scopes_dir, derived_scope_dir, load_scope, project_root


class ObsidianCliUnavailableError(RuntimeError):
    pass


class CodexCliUnavailableError(RuntimeError):
    pass


def _target_vault_context(vault: str | None, cwd: str | Path | None = None) -> tuple[str | None, str | Path | None]:
    if not vault:
        return None, cwd
    vault_path = Path(vault).expanduser()
    if vault_path.exists() and vault_path.is_dir():
        return None, vault_path
    return vault, cwd


@lru_cache(maxsize=4)
def _obsidian_binary() -> str:
    binary = shutil.which("obsidian")
    if not binary:
        raise ObsidianCliUnavailableError(
            "Official Obsidian CLI was not found in PATH. Enable it in Obsidian Settings > General > Command line interface."
        )

    resolved = str(Path(binary).resolve())
    if "node_modules/obsidian-cli" in resolved:
        raise ObsidianCliUnavailableError(
            f"Found non-official obsidian binary at {resolved}. This project requires the official Obsidian desktop CLI, not the npm obsidian-cli package."
        )

    probe = subprocess.run([binary, "help"], capture_output=True, text=True)
    combined = (probe.stdout or "") + (probe.stderr or "")
    if "OBSIDIAN_API_KEY" in combined or "OBSIDIAN_API_SECRET" in combined or "Unable to find a module to process this command!" in combined:
        raise ObsidianCliUnavailableError(
            f"Found incompatible obsidian binary at {resolved}. This project requires the official Obsidian desktop CLI, not an API-key-based npm CLI."
        )
    return binary


def _run(command: list[str], cwd: str | Path | None = None) -> QueryResult:
    proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    return QueryResult(command=command, stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)


def search(
    query: str,
    vault: str | None = None,
    cwd: str | Path | None = None,
    path: str | None = None,
    format: str | None = None,
    limit: int | None = None,
) -> QueryResult:
    cmd = [_obsidian_binary()]
    vault_arg, command_cwd = _target_vault_context(vault, cwd)
    if vault_arg:
        cmd.append(f"vault={vault_arg}")
    cmd.append("search")
    cmd.append(f"query={query}")
    if path:
        cmd.append(f"path={path}")
    if format:
        cmd.append(f"format={format}")
    if limit:
        cmd.append(f"limit={limit}")
    return _run(cmd, command_cwd)


def read_note(path: str, vault: str | None = None, cwd: str | Path | None = None) -> QueryResult:
    cmd = [_obsidian_binary()]
    vault_arg, command_cwd = _target_vault_context(vault, cwd)
    if vault_arg:
        cmd.append(f"vault={vault_arg}")
    cmd.extend(["read", f"path={path}"])
    return _run(cmd, command_cwd)


def query_vault(prompt: str, scope: str | None = None, vault: str | None = None, cwd: str | Path | None = None) -> list[QueryResult]:
    search_term = prompt if not scope else f"{scope} {prompt}"
    search_result = search(search_term, vault=vault, cwd=cwd)
    results = [search_result]
    if search_result.returncode != 0:
        return results

    paths = _extract_paths_from_search_stdout(search_result.stdout)
    if not paths:
        return results
    results.append(read_note(paths[0], vault=vault, cwd=cwd))
    return results


def _extract_paths_from_search_stdout(stdout: str) -> list[str]:
    text = stdout.strip()
    if not text:
        return []
    if text.lower() == "no matches found.":
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        paths = []
        for line in text.splitlines():
            if not line.strip():
                continue
            head = line.split("\t", 1)[0].strip()
            if head.lower() == "no matches found.":
                continue
            if head:
                paths.append(head)
        return paths

    if isinstance(payload, list):
        paths: list[str] = []
        for item in payload:
            if isinstance(item, str):
                paths.append(item)
            elif isinstance(item, dict):
                path = item.get("path") or item.get("file") or item.get("note")
                if isinstance(path, str):
                    paths.append(path)
        return paths

    if isinstance(payload, dict):
        candidates = payload.get("results") or payload.get("items") or payload.get("matches") or []
        if isinstance(candidates, list):
            return _extract_paths_from_search_stdout(json.dumps(candidates, ensure_ascii=False))
    return []


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


def _snippet_from_text(content: str, query: str) -> str:
    _, body = _parse_frontmatter(content)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines:
        return ""
    lowered_query = query.lower()
    tokens = [token.lower() for token in re.split(r"\s+", query.strip()) if token.strip()]
    for line in lines:
        lowered = line.lower()
        if lowered_query and lowered_query in lowered:
            return line[:240]
        if tokens and any(token in lowered for token in tokens):
            return line[:240]
    return lines[0][:240]


def _score_content(content: str, query: str) -> float:
    lowered = content.lower()
    score = 0.0
    if query.lower() in lowered:
        score += 5.0
    for token in re.split(r"\s+", query.strip()):
        token = token.lower()
        if token:
            score += lowered.count(token)
    return score


def search_scope(
    scope_id: str,
    query: str,
    vault_path: str | Path,
    scopes_dir: str | Path | None = None,
    limit: int = 8,
) -> list[EvidenceItem]:
    scope = load_scope(scope_id, scopes_dir=scopes_dir)
    vault_root = Path(vault_path).expanduser()
    matches: dict[str, EvidenceItem] = {}

    per_source_limit = max(limit, 4)
    for source in scope.sources:
        result = search(query, cwd=vault_root, path=source.path, format="json", limit=per_source_limit)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip() or f"Search failed for scope {scope_id!r}.")
        for note_path in _extract_paths_from_search_stdout(result.stdout):
            if note_path in matches:
                continue
            note_result = read_note(note_path, cwd=vault_root)
            if note_result.returncode != 0:
                continue
            metadata, _ = _parse_frontmatter(note_result.stdout)
            matches[note_path] = EvidenceItem(
                path=note_path,
                title=metadata.get("title") or Path(note_path).stem,
                source=metadata.get("source") or source.source or "unknown",
                content_type=metadata.get("content_type") or "note",
                snippet=_snippet_from_text(note_result.stdout, query),
                score=_score_content(note_result.stdout, query),
                source_kind="raw",
            )

    ordered = sorted(matches.values(), key=lambda item: (-item.score, item.path))
    return ordered[:limit]


def open_derived_note(kind: str, scope_id: str, vault_path: str | Path) -> QueryResult:
    relative = str((Path("Derived") / "Scopes" / scope_id / f"{kind}.md").as_posix())
    return read_note(relative, cwd=Path(vault_path).expanduser())


def _codex_binary() -> str:
    binary = shutil.which("codex")
    if not binary:
        raise CodexCliUnavailableError("codex CLI was not found in PATH.")
    return binary


def _codex_exec_prefix(binary: str, cwd: Path, extra_dirs: list[Path]) -> list[str]:
    cmd = [binary, "exec", "-C", str(cwd)]
    for extra_dir in extra_dirs:
        cmd.extend(["--add-dir", str(extra_dir)])
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


def _helper_prefix() -> str:
    root = project_root()
    return f'PYTHONPATH="{root / "src"}" "{sys.executable}" -m obsidian_knowledge_ingestor.cli'


def _strip_frontmatter(text: str) -> str:
    _, body = _parse_frontmatter(text)
    return body.strip()


def _read_derived_note_body(kind: str, scope_id: str, vault_path: Path) -> str:
    note_path = derived_scope_dir(scope_id, vault_path) / f"{kind}.md"
    if not note_path.exists():
        raise RuntimeError(f"Derived scope note missing: {note_path}")
    return _strip_frontmatter(note_path.read_text(encoding="utf-8"))


def _truncate_for_prompt(text: str, max_chars: int) -> str:
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[:max_chars].rstrip() + "\n\n[Truncated for prompt length]"


def _build_agent_prompt(
    prompt: str,
    scope_id: str,
    context_mode: str,
    vault_path: Path,
    preloaded_context: dict[str, str] | None = None,
) -> str:
    helper = _helper_prefix()
    vault_arg = shlex.quote(str(vault_path))
    derived_dir = derived_scope_dir(scope_id, vault_path)
    intro_lines = [
        f'You are answering a serious, source-grounded question for the scope "{scope_id}".',
        "You must stay inside this scope and use only the retrieval helpers below for vault access.",
        "This is a long-form reasoning task. Optimize for depth, structure, and real intellectual synthesis, not brevity.",
        "",
        "Allowed retrieval commands:",
        f'- {helper} qa-search --scope {scope_id} --query "<query>" --vault {vault_arg}',
        f'- {helper} qa-read --path "<vault-note-path>" --vault {vault_arg} --body-only',
        "",
        "Execution protocol:",
        "1. Start from the preloaded derived map included below. This is mandatory context, not final evidence.",
        "2. Reframe the user question into underlying motives, tensions, and long-term criteria before searching.",
        "3. Run multiple rounds of qa-search using short, high-signal queries, not one long natural-language question only.",
        "4. Read raw notes from different query buckets before answering.",
        "5. Keep searching if you do not yet have enough raw evidence.",
        "",
        "Required query buckets:",
        "- Surface behavior terms from the user question.",
        "- Underlying motive terms such as boredom, escape, calm, loneliness, freedom, rhythm, meaning, pleasure, friendship, or self-knowledge when relevant.",
        "- Evaluative terms that match the author's likely vocabulary and criteria.",
        "- Counterpoint terms that test whether the opposite framing changes the answer.",
        "",
        "Minimum evidence protocol:",
        "- Perform at least 4 distinct qa-search calls.",
        "- Read at least 4 distinct raw notes unless the scope genuinely lacks relevant material.",
        "- Do not treat derived notes as final evidence.",
        "- Every important conclusion must point back to raw note paths.",
        "- If a search query fails, adjust the query and continue rather than stopping early.",
        "",
        "Output contract:",
        "- Write in Chinese.",
        "- Make the answer substantial and insight-oriented, not terse.",
        "- Aim for roughly 1200-2500 Chinese characters when the evidence supports it.",
        "- Output in Markdown with these sections exactly:",
        "  1. ## Analysis Trace",
        "  2. ## Answer",
        "  3. ## Citations",
        "- In ## Analysis Trace include:",
        "  - question reframing",
        "  - search strategy",
        "  - evidence synthesis",
        "  - tensions, ambiguities, or limits",
        "- In ## Citations list raw note paths only.",
        "",
        f"The scope package is located under `{derived_dir.relative_to(vault_path)}`.",
    ]

    if context_mode == "fulltext":
        intro_lines.extend(
            [
                "",
                "Context mode: fulltext",
                "- The prompt below already includes overview, themes, and a preloaded full-context extract.",
                "- Build a whole-corpus understanding first, then search raw notes for precise supporting evidence.",
            ]
        )
    else:
        intro_lines.extend(
            [
                "",
                "Context mode: map",
                "- The prompt below already includes overview, themes, and corpus index extracts.",
                "- Use the map to derive multiple query families, then read raw notes for evidence.",
            ]
        )

    if preloaded_context:
        intro_lines.extend(
            [
                "",
                "Preloaded derived context:",
            ]
        )
        for kind, body in preloaded_context.items():
            intro_lines.extend(
                [
                    "",
                    f"### BEGIN {kind.upper()}",
                    body,
                    f"### END {kind.upper()}",
                ]
            )

    intro_lines.extend(["", "User question:", prompt.strip()])
    return "\n".join(intro_lines)


def ask_scope(
    prompt: str,
    scope_id: str,
    vault_path: str | Path,
    context_mode: str = "map",
    agent: str = "codex",
    scopes_dir: str | Path | None = None,
) -> AskResultBundle:
    vault_root = Path(vault_path).expanduser()
    if not derived_scope_dir(scope_id, vault_root).exists():
        raise RuntimeError(f"Derived scope package missing for {scope_id!r}. Run `oki build-qa --scope {scope_id}` first.")

    if scopes_dir is None:
        scopes_dir = default_scopes_dir()
    load_scope(scope_id, scopes_dir=scopes_dir)

    if agent == "none":
        answer = _build_agent_prompt(prompt, scope_id, context_mode=context_mode, vault_path=vault_root)
        return AskResultBundle(prompt=prompt, scope_id=scope_id, context_mode=context_mode, agent=agent, answer_markdown=answer)

    binary = _codex_binary()
    preloaded_context = {
        "overview": _truncate_for_prompt(_read_derived_note_body("overview", scope_id, vault_root), 32000),
        "themes": _truncate_for_prompt(_read_derived_note_body("themes", scope_id, vault_root), 40000),
    }
    if context_mode == "fulltext":
        preloaded_context["full_context"] = _truncate_for_prompt(_read_derived_note_body("full_context", scope_id, vault_root), 70000)
    else:
        preloaded_context["corpus_index"] = _truncate_for_prompt(_read_derived_note_body("corpus_index", scope_id, vault_root), 24000)
    prompt_text = _build_agent_prompt(
        prompt,
        scope_id,
        context_mode=context_mode,
        vault_path=vault_root,
        preloaded_context=preloaded_context,
    )
    env = dict(os.environ)
    root = project_root()
    src_root = root / "src"
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(src_root) if not existing_pythonpath else f"{src_root}:{existing_pythonpath}"
    if scopes_dir:
        env["OKI_SCOPES_DIR"] = str(Path(scopes_dir).expanduser())
    stream_output = _should_stream_codex_output()

    with tempfile.TemporaryDirectory() as tmp_dir:
        output_path = Path(tmp_dir) / "codex-last-message.md"
        cmd = _codex_exec_prefix(binary, root, [vault_root])
        cmd.extend(["--output-last-message", str(output_path), "-"])
        result = subprocess.run(
            cmd,
            cwd=root,
            env=env,
            input=prompt_text,
            capture_output=not stream_output,
            text=True,
        )
        if result.returncode != 0:
            message = ""
            if not stream_output:
                message = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(message or "codex exec failed while answering the scope question.")
        answer = output_path.read_text(encoding="utf-8")
    return AskResultBundle(prompt=prompt, scope_id=scope_id, context_mode=context_mode, agent=agent, answer_markdown=answer)


def ask_scope_as_json(
    prompt: str,
    scope_id: str,
    vault_path: str | Path,
    context_mode: str = "map",
    agent: str = "codex",
    scopes_dir: str | Path | None = None,
) -> str:
    bundle = ask_scope(prompt, scope_id, vault_path, context_mode=context_mode, agent=agent, scopes_dir=scopes_dir)
    return json.dumps(asdict(bundle), ensure_ascii=False, indent=2)
