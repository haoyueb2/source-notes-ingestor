from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from .models import AskResultBundle, EvidenceItem, QueryResult
from .scope_loader import default_scopes_dir, derived_scope_dir, load_scope, project_root


class ObsidianCliUnavailableError(RuntimeError):
    pass


class CodexCliUnavailableError(RuntimeError):
    pass


PROMPT_CONCEPT_KEYWORDS = [
    "失败",
    "内耗",
    "焦虑",
    "机会",
    "错过",
    "聪明人",
    "回国",
    "美国",
    "硅谷",
    "工作",
    "职业",
    "路线",
    "代价",
    "自由",
    "认同",
    "外界认同",
    "成长",
    "努力",
    "节奏",
    "独处",
    "孤独",
    "时间",
    "快乐",
    "人生",
    "意义",
    "命运",
]

QUERY_STOPWORDS = {
    "一路走来",
    "很多",
    "最大",
    "一次",
    "感觉",
    "觉得",
    "就是",
    "然后",
    "但是",
    "因为",
    "所以",
    "还是",
    "如何",
    "怎么办",
    "什么",
    "这个",
    "那个",
}


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


def _build_codex_env(scopes_dir: str | Path | None = None) -> tuple[dict[str, str], Path]:
    env = dict(os.environ)
    root = project_root()
    src_root = root / "src"
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(src_root) if not existing_pythonpath else f"{src_root}:{existing_pythonpath}"
    if scopes_dir:
        env["OKI_SCOPES_DIR"] = str(Path(scopes_dir).expanduser())
    return env, root


def _run_codex_json(
    prompt: str,
    schema: dict[str, object],
    extra_dirs: list[Path],
    scopes_dir: str | Path | None = None,
    stream_output: bool | None = None,
) -> dict[str, object]:
    binary = _codex_binary()
    env, root = _build_codex_env(scopes_dir=scopes_dir)
    if stream_output is None:
        stream_output = _should_stream_codex_output()
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_root = Path(tmp_dir)
        schema_path = tmp_root / "schema.json"
        output_path = tmp_root / "response.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
        result = subprocess.run(
            _codex_exec_prefix(binary, root, extra_dirs)
            + [
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "-",
            ],
            cwd=root,
            env=env,
            input=prompt,
            capture_output=not stream_output,
            text=True,
        )
        if result.returncode != 0:
            message = ""
            if not stream_output:
                message = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(message or "codex exec failed while generating structured retrieval output.")
        return json.loads(output_path.read_text(encoding="utf-8"))


def _run_codex_markdown(
    prompt: str,
    extra_dirs: list[Path],
    scopes_dir: str | Path | None = None,
    stream_output: bool | None = None,
) -> str:
    binary = _codex_binary()
    env, root = _build_codex_env(scopes_dir=scopes_dir)
    if stream_output is None:
        stream_output = _should_stream_codex_output()
    with tempfile.TemporaryDirectory() as tmp_dir:
        output_path = Path(tmp_dir) / "codex-last-message.md"
        cmd = _codex_exec_prefix(binary, root, extra_dirs)
        cmd.extend(["--output-last-message", str(output_path), "-"])
        result = subprocess.run(
            cmd,
            cwd=root,
            env=env,
            input=prompt,
            capture_output=not stream_output,
            text=True,
        )
        if result.returncode != 0:
            message = ""
            if not stream_output:
                message = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(message or "codex exec failed while synthesizing the scope answer.")
        return output_path.read_text(encoding="utf-8")


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


def _add_query_candidate(candidates: list[str], seen: set[str], value: str) -> None:
    query = value.strip()
    if not query or query in seen:
        return
    seen.add(query)
    candidates.append(query)


def _split_query_terms(query: str) -> list[str]:
    pieces = re.split(r"[\s,，、/|;；]+", query.strip())
    terms: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        token = piece.strip()
        if len(token) < 2 or token in QUERY_STOPWORDS or token in seen:
            continue
        seen.add(token)
        terms.append(token)
    return terms


def _prompt_keyword_queries(prompt: str) -> list[str]:
    normalized = prompt.strip()
    candidates: list[str] = []
    seen: set[str] = set()
    for keyword in PROMPT_CONCEPT_KEYWORDS:
        if keyword in normalized:
            _add_query_candidate(candidates, seen, keyword)

    for english in re.findall(r"[A-Za-z][A-Za-z0-9.+-]{1,}", normalized):
        _add_query_candidate(candidates, seen, english)

    clauses = [part.strip() for part in re.split(r"[，。,．；;：:\n!?！？（）()“”\"'、]+", normalized) if part.strip()]
    for clause in clauses:
        if 2 <= len(clause) <= 12 and clause not in QUERY_STOPWORDS:
            _add_query_candidate(candidates, seen, clause)
        for token in _split_query_terms(clause):
            _add_query_candidate(candidates, seen, token)
    return candidates[:16]


def _fallback_queries(prompt: str) -> list[str]:
    normalized = prompt.strip()
    queries: list[str] = []
    seen: set[str] = set()
    if normalized:
        _add_query_candidate(queries, seen, normalized)
    for keyword in _prompt_keyword_queries(normalized):
        _add_query_candidate(queries, seen, keyword)
    return queries[:12]


def _normalize_query_plan(payload: dict[str, object], prompt: str) -> tuple[str, list[dict[str, str]]]:
    reframing = str(payload.get("question_reframing") or prompt).strip()
    raw_plan = payload.get("query_plan")
    queries: list[dict[str, str]] = []
    seen: set[str] = set()
    if isinstance(raw_plan, list):
        for item in raw_plan:
            if not isinstance(item, dict):
                continue
            query = str(item.get("query") or "").strip()
            if not query or query in seen:
                continue
            seen.add(query)
            queries.append(
                {
                    "query": query,
                    "bucket": str(item.get("bucket") or "unspecified").strip() or "unspecified",
                    "why": str(item.get("why") or "").strip(),
                }
            )
            for token in _split_query_terms(query):
                if token in seen:
                    continue
                seen.add(token)
                queries.append(
                    {
                        "query": token,
                        "bucket": f"{str(item.get('bucket') or 'unspecified').strip() or 'unspecified'}-term",
                        "why": f"Short-form fallback term derived from planned query: {query}",
                    }
                )
    for query in _fallback_queries(prompt):
        if query in seen:
            continue
        seen.add(query)
        queries.append({"query": query, "bucket": "fallback", "why": "Fallback query derived from the user prompt."})
        if len(queries) >= 14:
            break
    return reframing, queries[:14]


def _build_retrieval_plan_prompt(
    prompt: str,
    scope_id: str,
    context_mode: str,
    preloaded_context: dict[str, str],
) -> str:
    lines = [
        f'You are planning retrieval for a serious scope-grounded question about "{scope_id}".',
        "Your job is not to answer yet.",
        "Your job is to produce a high-quality retrieval plan that helps a downstream program gather the right raw notes.",
        "Return JSON only.",
        "",
        "Planning requirements:",
        "- Write query strings that are short, retrieval-friendly, and semantically sharp.",
        "- Cover surface wording, hidden motives, evaluative criteria, and counterpoints.",
        "- Prefer 6-8 queries unless the material is unusually narrow.",
        "- Keep queries diverse. Do not repeat near-duplicates.",
        "- Write in Chinese when appropriate to the source material.",
        "",
        "JSON contract:",
        '- `question_reframing`: a concise but deep reframing of the user question.',
        '- `query_plan`: array of objects with `query`, `bucket`, and `why`.',
        "",
        f"Context mode: {context_mode}",
        "Use the derived context below as navigation only.",
    ]
    for kind, body in preloaded_context.items():
        lines.extend(["", f"### BEGIN {kind.upper()}", body, f"### END {kind.upper()}"])
    lines.extend(["", "User question:", prompt.strip()])
    return "\n".join(lines)


def _progress(message: str) -> None:
    print(f"[oki ask] {message}", file=sys.stderr)


def _search_scope_with_retry(
    scope_id: str,
    query: str,
    vault_path: Path,
    scopes_dir: str | Path | None,
    limit: int,
    retries: int = 2,
) -> list[EvidenceItem]:
    last_error: RuntimeError | None = None
    for attempt in range(retries + 1):
        try:
            return search_scope(scope_id, query, vault_path, scopes_dir=scopes_dir, limit=limit)
        except RuntimeError as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(0.2 * (attempt + 1))
    raise last_error or RuntimeError(f"Search failed for scope {scope_id!r}.")


def _collect_preloaded_context(scope_id: str, vault_root: Path, context_mode: str) -> dict[str, str]:
    preloaded_context = {
        "overview": _truncate_for_prompt(_read_derived_note_body("overview", scope_id, vault_root), 32000),
        "themes": _truncate_for_prompt(_read_derived_note_body("themes", scope_id, vault_root), 40000),
    }
    if context_mode == "fulltext":
        preloaded_context["full_context"] = _truncate_for_prompt(_read_derived_note_body("full_context", scope_id, vault_root), 70000)
    else:
        preloaded_context["corpus_index"] = _truncate_for_prompt(_read_derived_note_body("corpus_index", scope_id, vault_root), 24000)
    return preloaded_context


def _collect_evidence_bundle(
    scope_id: str,
    queries: list[dict[str, str]],
    vault_root: Path,
    scopes_dir: str | Path | None,
    per_query_limit: int = 6,
    final_note_limit: int = 8,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    aggregate: dict[str, dict[str, object]] = {}
    query_runs: list[dict[str, object]] = []
    for item in queries:
        query = item["query"]
        _progress(f"searching `{query}`")
        results = _search_scope_with_retry(scope_id, query, vault_root, scopes_dir=scopes_dir, limit=per_query_limit)
        query_runs.append(
            {
                "query": query,
                "bucket": item.get("bucket", ""),
                "why": item.get("why", ""),
                "match_count": len(results),
                "paths": [result.path for result in results],
            }
        )
        for result in results:
            existing = aggregate.get(result.path)
            if existing is None:
                aggregate[result.path] = {
                    "item": result,
                    "total_score": result.score,
                    "queries": [query],
                    "snippets": [result.snippet] if result.snippet else [],
                }
                continue
            existing["total_score"] = float(existing["total_score"]) + result.score
            if query not in existing["queries"]:
                existing["queries"].append(query)
            if result.snippet and result.snippet not in existing["snippets"]:
                existing["snippets"].append(result.snippet)

    if not aggregate:
        raise RuntimeError(f"No raw evidence found for scope {scope_id!r}.")

    ordered = sorted(
        aggregate.values(),
        key=lambda entry: (-len(entry["queries"]), -float(entry["total_score"]), entry["item"].path),
    )

    bundle: list[dict[str, object]] = []
    for entry in ordered[:final_note_limit]:
        evidence_item = entry["item"]
        note_result = read_note(evidence_item.path, cwd=vault_root)
        if note_result.returncode != 0:
            continue
        bundle.append(
            {
                "path": evidence_item.path,
                "title": evidence_item.title,
                "source": evidence_item.source,
                "content_type": evidence_item.content_type,
                "queries": entry["queries"],
                "snippets": entry["snippets"][:3],
                "body_excerpt": _truncate_for_prompt(_strip_frontmatter(note_result.stdout), 2200),
            }
        )
    if not bundle:
        raise RuntimeError(f"Unable to read raw evidence notes for scope {scope_id!r}.")
    return query_runs, bundle


def _build_synthesis_prompt(
    user_prompt: str,
    scope_id: str,
    question_reframing: str,
    query_runs: list[dict[str, object]],
    evidence_bundle: list[dict[str, object]],
) -> str:
    lines = [
        f'You are answering a serious, source-grounded question for the scope "{scope_id}".',
        "You are no longer planning retrieval. The program has already gathered raw evidence for you.",
        "You must answer only from the raw evidence bundle below.",
        "Do not invent positions that are not supported by the cited raw notes.",
        "",
        "Answer requirements:",
        "- Write in Chinese.",
        "- Optimize for depth, structure, and serious thinking, not brevity.",
        "- Push beyond surface advice into motives, criteria, tensions, tradeoffs, and long-term implications.",
        "- Aim for roughly 1500-2800 Chinese characters when the evidence supports it.",
        "- Keep the voice analytical rather than theatrical.",
        "",
        "Output contract:",
        "- Output in Markdown with these sections exactly:",
        "  1. ## Analysis Trace",
        "  2. ## Answer",
        "  3. ## Citations",
        "- In ## Analysis Trace include:",
        "  - question reframing",
        "  - retrieval summary",
        "  - evidence synthesis",
        "  - tensions, ambiguities, or limits",
        "- In ## Citations list raw note paths only.",
        "",
        "User question:",
        user_prompt.strip(),
        "",
        "Question reframing:",
        question_reframing,
        "",
        "Retrieval summary:",
    ]
    for run in query_runs:
        lines.append(
            f"- query `{run['query']}` ({run['bucket']}): {run['match_count']} matches"
        )
    lines.extend(["", "Raw evidence bundle:"])
    for idx, record in enumerate(evidence_bundle, start=1):
        lines.extend(
            [
                "",
                f"### Evidence {idx:02d}",
                f"- Path: `{record['path']}`",
                f"- Title: {record['title']}",
                f"- Source: {record['source']}",
                f"- Type: {record['content_type']}",
                f"- Hit queries: {', '.join(record['queries'])}",
                "- Key snippets:",
            ]
        )
        for snippet in record["snippets"]:
            lines.append(f"  - {snippet}")
        lines.extend(["- Body excerpt:", record["body_excerpt"]])
    return "\n".join(lines)


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

    preloaded_context = _collect_preloaded_context(scope_id, vault_root, context_mode=context_mode)
    _progress("planning retrieval")
    plan_payload = _run_codex_json(
        _build_retrieval_plan_prompt(prompt, scope_id, context_mode=context_mode, preloaded_context=preloaded_context),
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["question_reframing", "query_plan"],
            "properties": {
                "question_reframing": {"type": "string"},
                "query_plan": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["query", "bucket", "why"],
                        "properties": {
                            "query": {"type": "string"},
                            "bucket": {"type": "string"},
                            "why": {"type": "string"},
                        },
                    },
                },
            },
        },
        extra_dirs=[vault_root],
        scopes_dir=scopes_dir,
        stream_output=True,
    )
    question_reframing, query_plan = _normalize_query_plan(plan_payload, prompt)
    query_runs, evidence_bundle = _collect_evidence_bundle(scope_id, query_plan, vault_root, scopes_dir=scopes_dir)
    _progress("synthesizing final answer")
    answer = _run_codex_markdown(
        _build_synthesis_prompt(prompt, scope_id, question_reframing, query_runs, evidence_bundle),
        extra_dirs=[vault_root],
        scopes_dir=scopes_dir,
        stream_output=False,
    )
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
