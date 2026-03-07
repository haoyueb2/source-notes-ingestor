from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AppConfig:
    vault_path: Path
    state_dir: Path
    raw_data_dir: Path
    asset_dir_name: str = "Sources/_assets"
    sync_state_dir_name: str = "Sources/_state"
    log_level: str = "info"

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            vault_path=Path(os.environ.get("OBSIDIAN_VAULT_PATH", "./vault")).expanduser(),
            state_dir=Path(os.environ.get("STATE_DIR", "./state")).expanduser(),
            raw_data_dir=Path(os.environ.get("RAW_DATA_DIR", "./samples")).expanduser(),
            asset_dir_name=os.environ.get("ASSET_DIR_NAME", "Sources/_assets"),
            sync_state_dir_name=os.environ.get("SYNC_STATE_DIR_NAME", "Sources/_state"),
            log_level=os.environ.get("LOG_LEVEL", "info"),
        )


def load_target(path: str | Path) -> dict[str, Any]:
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        return json.load(handle)
