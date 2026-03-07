from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .models import QueryResult


class ObsidianCliUnavailableError(RuntimeError):
    pass


def _obsidian_binary() -> str:
    binary = shutil.which("obsidian")
    if not binary:
        raise ObsidianCliUnavailableError(
            "obsidian CLI was not found in PATH. Enable it in Obsidian Settings > General > Command line interface."
        )
    return binary


def _run(command: list[str], cwd: str | Path | None = None) -> QueryResult:
    proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    return QueryResult(command=command, stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)


def search(query: str, vault: str | None = None, cwd: str | Path | None = None) -> QueryResult:
    cmd = [_obsidian_binary()]
    if vault:
        cmd.append(f"vault={vault}")
    cmd.extend(["search", f"query={query}"])
    return _run(cmd, cwd)


def read_note(path: str, vault: str | None = None, cwd: str | Path | None = None) -> QueryResult:
    cmd = [_obsidian_binary()]
    if vault:
        cmd.append(f"vault={vault}")
    cmd.extend(["read", f"path={path}"])
    return _run(cmd, cwd)


def query_vault(prompt: str, scope: str | None = None, vault: str | None = None, cwd: str | Path | None = None) -> list[QueryResult]:
    search_term = prompt if not scope else f"{scope} {prompt}"
    search_result = search(search_term, vault=vault, cwd=cwd)
    results = [search_result]
    if search_result.returncode != 0 or not search_result.stdout.strip():
        return results

    lines = [line.strip() for line in search_result.stdout.splitlines() if line.strip()]
    top = lines[0]
    if "\t" in top:
        top = top.split("\t", 1)[0]
    results.append(read_note(top, vault=vault, cwd=cwd))
    return results
