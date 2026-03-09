from __future__ import annotations

import json
import os
from pathlib import Path

from .models import ScopeConfig, ScopeSource


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_scopes_dir(root: Path | None = None) -> Path:
    override = os.environ.get("OKI_SCOPES_DIR")
    if override:
        return Path(override).expanduser()
    return (root or project_root()) / "scopes"


def load_scope(scope_id: str, scopes_dir: str | Path | None = None) -> ScopeConfig:
    base_dir = Path(scopes_dir).expanduser() if scopes_dir else default_scopes_dir()
    scope_path = base_dir / f"{scope_id}.json"
    if not scope_path.exists():
        raise FileNotFoundError(f"Scope config not found: {scope_path}")

    payload = json.loads(scope_path.read_text(encoding="utf-8"))
    sources = [ScopeSource(**entry) for entry in payload.get("sources", [])]
    if not sources:
        raise ValueError(f"Scope {scope_id!r} does not define any sources.")

    return ScopeConfig(
        scope_id=payload.get("scope_id", scope_id),
        display_name=payload.get("display_name") or scope_id,
        description=payload.get("description"),
        sources=sources,
    )


def resolve_scope_source_path(source: ScopeSource, vault_path: str | Path) -> Path:
    raw = Path(source.path).expanduser()
    if raw.is_absolute():
        return raw
    return Path(vault_path).expanduser() / raw


def derived_scope_dir(scope_id: str, vault_path: str | Path) -> Path:
    return Path(vault_path).expanduser() / "Derived" / "Scopes" / scope_id
