"""Strategi screening siap pakai yang disimpan sebagai file YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import PRESET_DIR

DEFAULT_COLUMNS = [
    "ticker", "name", "sector", "close", "change_pct",
    "per", "pbv", "roe", "avg_value_20",
]


@dataclass
class Preset:
    name: str
    title: str = ""
    description: str = ""
    filters: list[str] = field(default_factory=list)
    sort_by: str | None = None
    ascending: bool = False
    limit: int | None = None
    columns: list[str] = field(default_factory=lambda: list(DEFAULT_COLUMNS))
    note: str = ""
    source: Path | None = None

    @classmethod
    def from_dict(cls, data: dict, source: Path | None = None) -> "Preset":
        sort = data.get("sort") or {}
        if isinstance(sort, str):
            sort = {"by": sort}
        return cls(
            name=data["name"],
            title=data.get("title", data["name"]),
            description=data.get("description", ""),
            filters=list(data.get("filters") or []),
            sort_by=sort.get("by"),
            ascending=bool(sort.get("ascending", False)),
            limit=data.get("limit"),
            columns=list(data.get("columns") or DEFAULT_COLUMNS),
            note=data.get("note", ""),
            source=source,
        )


def load_presets(directory: str | Path | None = None) -> dict[str, Preset]:
    directory = Path(directory) if directory else PRESET_DIR
    presets: dict[str, Preset] = {}
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data.setdefault("name", path.stem)
        preset = Preset.from_dict(data, source=path)
        presets[preset.name] = preset
    return presets


def get_preset(name: str, directory: str | Path | None = None) -> Preset:
    presets = load_presets(directory)
    if name not in presets:
        available = ", ".join(sorted(presets)) or "(kosong)"
        raise KeyError(f"Preset '{name}' tidak ada. Tersedia: {available}")
    return presets[name]
