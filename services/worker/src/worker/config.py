"""Loads shop configuration and the material property table from the repo root."""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

import yaml


def repo_root() -> Path:
    """Locate the repo root from an env var, or by walking up to the config directory."""
    env = os.environ.get("PRINTSHOP_ROOT")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "config" / "shop.yaml").exists():
            return parent
    raise RuntimeError(
        "Could not locate the repo root. Set PRINTSHOP_ROOT to the directory containing config/."
    )


@functools.lru_cache(maxsize=1)
def shop_config() -> dict[str, Any]:
    with (repo_root() / "config" / "shop.yaml").open() as fh:
        return yaml.safe_load(fh)


@functools.lru_cache(maxsize=1)
def materials_config() -> dict[str, Any]:
    with (repo_root() / "data" / "materials.yaml").open() as fh:
        return yaml.safe_load(fh)


def reload_config() -> None:
    """Drop cached config. Used by tests and by the admin 'reload' action."""
    shop_config.cache_clear()
    materials_config.cache_clear()
