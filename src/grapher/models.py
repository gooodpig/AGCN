from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Viewport:
    x_min: float = -10.0
    x_max: float = 10.0
    y_min: float = -10.0
    y_max: float = 10.0
    axes_visible: bool = False
    grid_visible: bool = False


@dataclass
class GgbObject:
    name: str
    kind: str
    attrs: dict = field(default_factory=dict)

    @property
    def visible(self) -> bool:
        return bool(self.attrs.get("visible", True))

    @property
    def label_visible(self) -> bool:
        return bool(self.attrs.get("label_visible", False))


@dataclass
class AsyResult:
    code: str
    objects: list[GgbObject]
    warnings: list[str] = field(default_factory=list)
