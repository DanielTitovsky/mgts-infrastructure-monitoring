from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Annotation:
    class_id: int
    x_center: float
    y_center: float
    width: float
    height: float


@dataclass
class Sample:
    source_path: str
    split: str
    image_bytes: bytes
    width: int
    height: int
    boxes: list[Annotation]
    family_id: str | None = None
    format_counts: dict[str, int] = field(default_factory=dict)
    source_flags: dict[str, int] = field(default_factory=dict)
