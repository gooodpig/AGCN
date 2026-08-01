from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

from .models import GgbObject, Viewport


@dataclass
class ParsedGgb:
    objects: list[GgbObject]
    viewport: Viewport
    warnings: list[str]
    xml_name: str


def _strip_namespaces(root: ET.Element) -> None:
    for node in root.iter():
        if "}" in node.tag:
            node.tag = node.tag.rsplit("}", 1)[1]


def _float(value: str | None, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.lower() in {"true", "1", "yes"}


def _numbered_attributes(node: ET.Element | None) -> list[str]:
    if node is None:
        return []

    def key(item: tuple[str, str]) -> tuple[int, str]:
        name = item[0]
        suffix = name[1:] if name.startswith("a") else name
        return (int(suffix), name) if suffix.isdigit() else (10**9, name)

    return [value for _, value in sorted(node.attrib.items(), key=key) if value]


def _numeric_attributes(node: ET.Element | None) -> dict[str, float]:
    if node is None:
        return {}
    result: dict[str, float] = {}
    for key, value in node.attrib.items():
        parsed = _float(value)
        if parsed is not None:
            result[key] = parsed
    return result


def _parse_viewport(root: ET.Element) -> Viewport:
    view = root.find("./euclidianView")
    if view is None:
        return Viewport()

    size = view.find("size")
    coords = view.find("coordSystem")
    settings = view.find("evSettings")
    width = _float(size.get("width") if size is not None else None)
    height = _float(size.get("height") if size is not None else None)
    x_zero = _float(coords.get("xZero") if coords is not None else None)
    y_zero = _float(coords.get("yZero") if coords is not None else None)
    x_scale = _float(coords.get("scale") if coords is not None else None)
    y_scale = _float(coords.get("yscale") if coords is not None else None, x_scale)

    if not all(
        value is not None and value != 0
        for value in (width, height, x_zero, y_zero, x_scale, y_scale)
    ):
        return Viewport(
            axes_visible=_bool(settings.get("axes") if settings is not None else None, False),
            grid_visible=_bool(settings.get("grid") if settings is not None else None, False),
        )

    return Viewport(
        x_min=-x_zero / x_scale,
        x_max=(width - x_zero) / x_scale,
        y_min=(y_zero - height) / y_scale,
        y_max=y_zero / y_scale,
        axes_visible=_bool(settings.get("axes") if settings is not None else None, False),
        grid_visible=_bool(settings.get("grid") if settings is not None else None, False),
    )


def _parse_command(command: ET.Element) -> dict:
    return {
        "name": command.get("name", ""),
        "inputs": _numbered_attributes(command.find("input")),
        "outputs": _numbered_attributes(command.find("output")),
    }


def _parse_style(element: ET.Element) -> dict:
    show = element.find("show")
    color = element.find("objColor")
    line_style = element.find("lineStyle")
    point_size = element.find("pointSize")
    point_style = element.find("pointStyle")
    label_offset = element.find("labelOffset")

    style: dict = {
        "visible": _bool(show.get("object") if show is not None else None, True),
        "label_visible": _bool(show.get("label") if show is not None else None, False),
    }
    if color is not None:
        style["color"] = (
            int(_float(color.get("r"), 0) or 0),
            int(_float(color.get("g"), 0) or 0),
            int(_float(color.get("b"), 0) or 0),
        )
        style["alpha"] = _float(color.get("alpha"), 0.0)
    if line_style is not None:
        style["line_thickness"] = _float(line_style.get("thickness"), 2.0)
        style["line_type"] = int(_float(line_style.get("type"), 0.0) or 0)
        style["line_opacity"] = _float(line_style.get("opacity"), 255.0)
    if point_size is not None:
        style["point_size"] = _float(point_size.get("val"), 4.0)
    if point_style is not None:
        style["point_style"] = int(_float(point_style.get("val"), 0.0) or 0)
    if label_offset is not None:
        style["label_offset"] = _numeric_attributes(label_offset)
    return style


def _parse_element(element: ET.Element, command: dict | None, expression: str | None) -> GgbObject:
    name = element.get("label") or element.get("name") or ""
    kind = (element.get("type") or "unknown").lower()
    attrs = _parse_style(element)
    attrs["coords"] = _numeric_attributes(element.find("coords"))
    attrs["matrix"] = _numeric_attributes(element.find("matrix"))
    attrs["eigenvectors"] = _numeric_attributes(element.find("eigenvectors"))
    attrs["parameters"] = _numeric_attributes(element.find("parameters"))

    value = element.find("value")
    if value is not None:
        attrs["value"] = _float(value.get("val"))
    if expression:
        attrs["expression"] = expression
    if command:
        attrs["command"] = command["name"]
        attrs["inputs"] = command["inputs"]
        attrs["outputs"] = command["outputs"]
        try:
            attrs["command_output_index"] = command["outputs"].index(name)
        except ValueError:
            attrs["command_output_index"] = 0

    return GgbObject(name=name, kind=kind, attrs=attrs)


def parse_ggb(path: str | Path) -> ParsedGgb:
    ggb_path = Path(path)
    warnings: list[str] = []
    try:
        with ZipFile(ggb_path) as archive:
            names = archive.namelist()
            xml_name = "geogebra.xml" if "geogebra.xml" in names else "construction.xml"
            if xml_name not in names:
                raise ValueError("The archive does not contain geogebra.xml.")
            root = ET.fromstring(archive.read(xml_name))
    except (BadZipFile, ET.ParseError, OSError) as error:
        raise ValueError(f"Cannot read GeoGebra file {ggb_path}: {error}") from error

    _strip_namespaces(root)
    construction = root.find("./construction")
    if construction is None:
        return ParsedGgb([], _parse_viewport(root), ["No construction section found."], xml_name)

    commands_by_output: dict[str, dict] = {}
    expressions: dict[str, str] = {}
    for child in construction:
        if child.tag == "command":
            command = _parse_command(child)
            for output in command["outputs"]:
                commands_by_output[output] = command
        elif child.tag == "expression":
            label = child.get("label")
            expression = child.get("exp")
            if label and expression:
                expressions[label] = expression

    objects = [
        _parse_element(
            element,
            commands_by_output.get(element.get("label", "")),
            expressions.get(element.get("label", "")),
        )
        for element in construction.findall("element")
    ]
    if not objects:
        warnings.append("No geometric objects found in the GeoGebra construction.")

    return ParsedGgb(objects, _parse_viewport(root), warnings, xml_name)
