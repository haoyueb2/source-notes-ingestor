from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RawItem:
    source: str
    author_id: str
    author_name: str
    content_id: str
    content_type: str
    title: str
    url: str
    published_at: datetime | None
    updated_at: datetime | None
    summary: str
    raw_html: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CanonicalNote:
    source: str
    author_id: str
    author_name: str
    content_id: str
    content_type: str
    title: str
    url: str
    published_at: datetime | None
    updated_at: datetime | None
    tags: list[str]
    summary: str
    markdown_body: str
    raw_html_path: Path | None
    assets: list[str]
    checksum: str


@dataclass(slots=True)
class QueryResult:
    command: list[str]
    stdout: str
    stderr: str
    returncode: int


@dataclass(slots=True)
class ScopeSource:
    path: str
    source: str | None = None
    author_name: str | None = None
    author_id: str | None = None
    account_name: str | None = None
    description: str | None = None


@dataclass(slots=True)
class ScopeConfig:
    scope_id: str
    display_name: str
    sources: list[ScopeSource]
    description: str | None = None


@dataclass(slots=True)
class DerivedScopeManifest:
    scope_id: str
    display_name: str
    derived_dir: str
    source_roots: list[str]
    source_note_paths: list[str]
    generated_files: dict[str, str]
    note_count: int
    source_counts: dict[str, int]


@dataclass(slots=True)
class AskUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0


@dataclass(slots=True)
class EvidenceItem:
    path: str
    title: str
    source: str
    content_type: str
    snippet: str
    score: float
    source_kind: str = "raw"


@dataclass(slots=True)
class AskTurn:
    turn_id: str
    parent_turn_id: str | None
    created_at: str
    user_prompt: str
    question_reframing: str
    query_plan: list[dict[str, str]] = field(default_factory=list)
    query_runs: list[dict[str, object]] = field(default_factory=list)
    evidence_bundle: list[dict[str, object]] = field(default_factory=list)
    answer_markdown_path: str | None = None
    answer_markdown: str | None = None
    usage: AskUsage = field(default_factory=AskUsage)
    used_retrieval: bool = True
    retrieval_reason: str | None = None


@dataclass(slots=True)
class AskSession:
    session_id: str
    scope_id: str
    context_mode: str
    agent: str
    created_at: str
    updated_at: str
    turns: list[AskTurn] = field(default_factory=list)
    title: str | None = None
    source_answer_path: str | None = None


@dataclass(slots=True)
class AskResultBundle:
    prompt: str
    scope_id: str
    context_mode: str
    agent: str
    answer_markdown: str
    answer_streamed: bool = False
    session_id: str | None = None
    turn_id: str | None = None
    used_retrieval: bool = True
    usage: AskUsage = field(default_factory=AskUsage)
    answer_markdown_path: str | None = None
    evidence_paths: list[str] = field(default_factory=list)
    question_reframing: str | None = None
    query_plan: list[dict[str, str]] = field(default_factory=list)
    query_runs: list[dict[str, object]] = field(default_factory=list)
    evidence_bundle: list[dict[str, object]] = field(default_factory=list)
    retrieval_reason: str | None = None
