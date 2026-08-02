from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
import unicodedata

from .models import AsyResult, GgbObject, Viewport
from .parser import ParsedGgb, parse_ggb


_CONIC_KINDS = {"conic", "conicpart", "implicitpoly"}


def _format_float(value: float) -> str:
    if abs(value) < 5e-12:
        value = 0.0
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.8g}"


def _escape_asy_string(value: str) -> str:
    return value.replace("\\", r"\\").replace('"', r'\"')


def _escape_tex(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "%": r"\%",
        "#": r"\#", "&": r"\&", "_": r"\_", "^": r"\^{}", "~": r"\~{}", "$": r"\$",
    }
    return "".join(replacements.get(char, char) for char in value)


class _NameMap:
    _reserved = {
        "E", "N", "S", "W", "NE", "NW", "SE", "SW", "O", "I",
        "currentpen", "currentpicture", "origin", "unitcircle", "cycle",
    }

    def __init__(self, names: list[str]):
        self._mapping: dict[str, str] = {}
        used: set[str] = set()
        for index, name in enumerate(dict.fromkeys(names), start=1):
            primes = name.count("'")
            normalized = unicodedata.normalize("NFKD", name.replace("'", ""))
            base = re.sub(r"[^A-Za-z0-9_]", "", normalized) + "p" * primes
            if not base:
                base = f"p{index}"
            if base[0].isdigit():
                base = f"p{base}"
            if base in self._reserved:
                base = f"p{base}"
            candidate = base
            suffix = 2
            while candidate in used:
                candidate = f"{base}{suffix}"
                suffix += 1
            used.add(candidate)
            self._mapping[name] = candidate

    def get(self, name: str) -> str:
        return self._mapping.get(name, name)


def _point_coords(obj: GgbObject) -> tuple[float, float] | None:
    coords = obj.attrs.get("coords", {})
    x = coords.get("x")
    y = coords.get("y")
    z = coords.get("z", 1.0)
    if x is None or y is None or z in (None, 0):
        return None
    return x / z, y / z


def _line_pattern(obj: GgbObject) -> str | None:
    line_type = int(obj.attrs.get("line_type", 0))
    return {
        10: "dashed",
        15: "dashed",
        20: "dotted",
        30: "dashdotted",
    }.get(line_type)


def _is_neutral_color(color: tuple[int, int, int]) -> bool:
    maximum = max(color)
    minimum = min(color)
    return maximum == 0 or maximum - minimum <= max(18, 0.12 * maximum)


def _color_pen(color: tuple[int, int, int]) -> str:
    red, green, blue = color
    return (
        f"rgb({_format_float(red / 255)},"
        f"{_format_float(green / 255)},"
        f"{_format_float(blue / 255)})"
    )


def _rgb_pen(obj: GgbObject, preserve_style: bool, point: bool = False) -> str:
    color_value = obj.attrs.get("color", (0, 0, 0))
    color = tuple(int(value) for value in color_value)
    pattern = _line_pattern(obj)
    if not preserve_style:
        if point:
            return f"{_color_pen(color)}+dotpen" if not _is_neutral_color(color) else "dotpen"
        pen = f"{_color_pen(color)}+thinline" if not _is_neutral_color(color) else "thinline"
        return f"{pattern}+{pen}" if pattern else pen
    color_pen = _color_pen(color)
    if point:
        size = float(obj.attrs.get("point_size", 4.0))
        return f"{color_pen}+linewidth({_format_float(max(2.4, size * 0.75))}bp)"
    thickness = float(obj.attrs.get("line_thickness", 2.0))
    pen = f"{color_pen}+linewidth({_format_float(max(0.35, thickness * 0.16))}bp)"
    return f"{pattern}+{pen}" if pattern else pen


def _line_box_intersections(a: float, b: float, c: float, view: Viewport) -> list[tuple[float, float]]:
    candidates: list[tuple[float, float]] = []
    tolerance = 1e-9
    if abs(b) > tolerance:
        for x in (view.x_min, view.x_max):
            y = -(a * x + c) / b
            if view.y_min - tolerance <= y <= view.y_max + tolerance:
                candidates.append((x, y))
    if abs(a) > tolerance:
        for y in (view.y_min, view.y_max):
            x = -(b * y + c) / a
            if view.x_min - tolerance <= x <= view.x_max + tolerance:
                candidates.append((x, y))

    unique: list[tuple[float, float]] = []
    for point in candidates:
        if not any(math.dist(point, other) < tolerance for other in unique):
            unique.append(point)
    if len(unique) <= 2:
        return unique
    return max(
        ([first, second] for index, first in enumerate(unique) for second in unique[index + 1:]),
        key=lambda pair: math.dist(pair[0], pair[1]),
    )


def _line_through_points(first: tuple[float, float], second: tuple[float, float], view: Viewport) -> list[tuple[float, float]]:
    x1, y1 = first
    x2, y2 = second
    return _line_box_intersections(y1 - y2, x2 - x1, x1 * y2 - x2 * y1, view)


def _pair_literal(point: tuple[float, float]) -> str:
    return f"({_format_float(point[0])}, {_format_float(point[1])})"


def _segment_inputs(obj: GgbObject) -> tuple[str, str] | None:
    inputs = list(obj.attrs.get("inputs", []))
    command = str(obj.attrs.get("command", "")).lower()
    if command in {"polygon", "polyline"} and len(inputs) >= 2:
        output_index = int(obj.attrs.get("command_output_index", 0))
        if output_index > 0:
            edge = output_index - 1
            end = (edge + 1) % len(inputs) if command == "polygon" else edge + 1
            if end < len(inputs):
                return inputs[edge], inputs[end]
    if len(inputs) >= 2:
        return inputs[0], inputs[1]
    return None


def _normalized_line(
    first: tuple[float, float],
    second: tuple[float, float],
) -> tuple[float, float, float] | None:
    x1, y1 = first
    x2, y2 = second
    a = y1 - y2
    b = x2 - x1
    norm = math.hypot(a, b)
    if norm < 1e-12:
        return None
    a, b, c = a / norm, b / norm, (x1 * y2 - x2 * y1) / norm
    if a < -1e-12 or (abs(a) <= 1e-12 and b < 0):
        a, b, c = -a, -b, -c
    return a, b, c


def _make_support(
    first: tuple[float, float],
    second: tuple[float, float],
    mode: str,
):
    line = _normalized_line(first, second)
    if line is None:
        return None
    return (*line, first, second, mode)


def _line_supports(
    objects: list[GgbObject],
    points: dict[str, tuple[float, float]],
) -> list[tuple]:
    supports: list[tuple] = []
    for obj in objects:
        if not obj.visible:
            continue
        inputs = list(obj.attrs.get("inputs", []))
        if obj.kind == "line":
            coords = obj.attrs.get("coords", {})
            if all(key in coords for key in ("x", "y", "z")):
                norm = math.hypot(coords["x"], coords["y"])
                if norm > 1e-12:
                    a, b, c = coords["x"] / norm, coords["y"] / norm, coords["z"] / norm
                    if a < -1e-12 or (abs(a) <= 1e-12 and b < 0):
                        a, b, c = -a, -b, -c
                    supports.append((a, b, c, None, None, "line"))
            elif len(inputs) >= 2 and all(name in points for name in inputs[:2]):
                support = _make_support(points[inputs[0]], points[inputs[1]], "line")
                if support:
                    supports.append(support)
        elif obj.kind in {"segment", "ray", "vector"}:
            endpoints = _segment_inputs(obj)
            if endpoints and all(name in points for name in endpoints):
                support = _make_support(
                    points[endpoints[0]],
                    points[endpoints[1]],
                    "ray" if obj.kind == "ray" else "segment",
                )
                if support:
                    supports.append(support)
        elif obj.kind in {"polygon", "polyline"}:
            vertices = [points[name] for name in inputs if name in points]
            edge_count = len(vertices) if obj.kind == "polygon" else len(vertices) - 1
            for index in range(max(0, edge_count)):
                support = _make_support(vertices[index], vertices[(index + 1) % len(vertices)], "segment")
                if support:
                    supports.append(support)
    return supports


def _point_on_support(
    point: tuple[float, float],
    support: tuple,
    tolerance: float,
) -> bool:
    a, b, c, first, second, mode = support
    if abs(a * point[0] + b * point[1] + c) > tolerance:
        return False
    if mode == "line":
        return True
    direction = (second[0] - first[0], second[1] - first[1])
    length_squared = direction[0] ** 2 + direction[1] ** 2
    if length_squared < 1e-12:
        return False
    parameter = (
        (point[0] - first[0]) * direction[0]
        + (point[1] - first[1]) * direction[1]
    ) / length_squared
    parameter_tolerance = tolerance / math.sqrt(length_squared)
    if mode == "ray":
        return parameter >= -parameter_tolerance
    return -parameter_tolerance <= parameter <= 1 + parameter_tolerance


def _distance_to_support(point: tuple[float, float], support: tuple) -> float:
    a, b, c, first, second, mode = support
    if mode == "line":
        return abs(a * point[0] + b * point[1] + c)
    direction = (second[0] - first[0], second[1] - first[1])
    length_squared = direction[0] ** 2 + direction[1] ** 2
    if length_squared < 1e-12:
        return math.dist(point, first)
    parameter = (
        (point[0] - first[0]) * direction[0]
        + (point[1] - first[1]) * direction[1]
    ) / length_squared
    if mode == "segment":
        parameter = min(1.0, max(0.0, parameter))
    else:
        parameter = max(0.0, parameter)
    projection = (
        first[0] + parameter * direction[0],
        first[1] + parameter * direction[1],
    )
    return math.dist(point, projection)


def _largest_free_sector_direction(
    point: tuple[float, float],
    supports: list[tuple],
    tolerance: float,
) -> tuple[float, float] | None:
    angles: list[float] = []
    for support in supports:
        if not _point_on_support(point, support, tolerance):
            continue
        a, b, _, first, second, mode = support
        vectors: list[tuple[float, float]] = []
        if mode == "line":
            vectors = [(b, -a), (-b, a)]
        else:
            distance_first = math.dist(point, first)
            distance_second = math.dist(point, second)
            if distance_first <= tolerance:
                vectors.append((second[0] - first[0], second[1] - first[1]))
            elif distance_second <= tolerance:
                vectors.append((first[0] - second[0], first[1] - second[1]))
            else:
                tangent = (b, -a)
                vectors.extend([tangent, (-tangent[0], -tangent[1])])
        for vector in vectors:
            if math.hypot(*vector) > 1e-12:
                angle = math.atan2(vector[1], vector[0]) % (2 * math.pi)
                if not any(abs((angle - existing + math.pi) % (2 * math.pi) - math.pi) < 1e-5 for existing in angles):
                    angles.append(angle)
    if len(angles) < 2:
        return None
    angles.sort()
    best_start = angles[0]
    best_gap = -1.0
    for index, start in enumerate(angles):
        end = angles[(index + 1) % len(angles)]
        if index == len(angles) - 1:
            end += 2 * math.pi
        gap = end - start
        if gap > best_gap:
            best_gap = gap
            best_start = start
    midpoint = best_start + best_gap / 2
    return math.cos(midpoint), math.sin(midpoint)


def _acute_anglemark(
    names: list[str],
    points: dict[str, tuple[float, float]],
    name_map: _NameMap,
    radius: float,
) -> str | None:
    if len(names) < 3 or not all(name in points for name in names[:3]):
        return None
    first_name, vertex_name, third_name = names[:3]
    first = points[first_name]
    vertex = points[vertex_name]
    third = points[third_name]
    first_vector = (first[0] - vertex[0], first[1] - vertex[1])
    third_vector = (third[0] - vertex[0], third[1] - vertex[1])
    if math.hypot(*first_vector) < 1e-12 or math.hypot(*third_vector) < 1e-12:
        return None

    if first_vector[0] * third_vector[0] + first_vector[1] * third_vector[1] < 0:
        first_vector = (-first_vector[0], -first_vector[1])
    cross = first_vector[0] * third_vector[1] - first_vector[1] * third_vector[0]
    if abs(cross) < 1e-12:
        return None
    if cross < 0:
        first_vector, third_vector = third_vector, first_vector

    start_angle = math.degrees(math.atan2(first_vector[1], first_vector[0]))
    end_angle = math.degrees(math.atan2(third_vector[1], third_vector[0]))
    while end_angle <= start_angle:
        end_angle += 360
    return (
        f"draw(arc({name_map.get(vertex_name)}, {_format_float(radius)}, "
        f"{_format_float(start_angle)}, {_format_float(end_angle)}), thinline);"
    )


def _conic_expression(matrix: dict[str, float]) -> str | None:
    required = [f"A{index}" for index in range(6)]
    if not all(key in matrix for key in required):
        return None
    a0, a1, a2, a3, a4, a5 = (matrix[key] for key in required)
    terms = [
        f"{_format_float(a0)}*x^2", f"{_format_float(a1)}*y^2",
        f"{_format_float(2 * a3)}*x*y", f"{_format_float(2 * a4)}*x",
        f"{_format_float(2 * a5)}*y", _format_float(a2),
    ]
    return "+".join(terms).replace("+-", "-")


def _conic_value_gradient(
    matrix: dict[str, float],
    point: tuple[float, float],
) -> tuple[float, float, float] | None:
    required = [f"A{index}" for index in range(6)]
    if not all(key in matrix for key in required):
        return None
    a0, a1, a2, a3, a4, a5 = (matrix[key] for key in required)
    x, y = point
    value = a0 * x * x + a1 * y * y + 2 * a3 * x * y + 2 * a4 * x + 2 * a5 * y + a2
    gradient_x = 2 * a0 * x + 2 * a3 * y + 2 * a4
    gradient_y = 2 * a1 * y + 2 * a3 * x + 2 * a5
    return value, gradient_x, gradient_y


def _conic_tangent_supports(
    point: tuple[float, float],
    matrices: list[dict[str, float]],
    scale: float,
) -> list[tuple]:
    supports: list[tuple] = []
    for matrix in matrices:
        evaluated = _conic_value_gradient(matrix, point)
        if evaluated is None:
            continue
        value, gradient_x, gradient_y = evaluated
        gradient_norm = math.hypot(gradient_x, gradient_y)
        if gradient_norm < 1e-12 or abs(value) / gradient_norm > 0.002 * scale:
            continue
        a = gradient_x / gradient_norm
        b = gradient_y / gradient_norm
        c = -(a * point[0] + b * point[1])
        supports.append((a, b, c, None, None, "line"))
    return supports


def _distance_to_conic(point: tuple[float, float], matrix: dict[str, float]) -> float:
    evaluated = _conic_value_gradient(matrix, point)
    if evaluated is None:
        return float("inf")
    value, gradient_x, gradient_y = evaluated
    gradient_norm = math.hypot(gradient_x, gradient_y)
    return abs(value) / gradient_norm if gradient_norm > 1e-12 else float("inf")

def _circle_from_matrix(matrix: dict[str, float]) -> tuple[tuple[float, float], float] | None:
    required = [f"A{index}" for index in range(6)]
    if not all(key in matrix for key in required):
        return None
    a0, a1, a2, a3, a4, a5 = (matrix[key] for key in required)
    scale = max(1.0, abs(a0), abs(a1))
    if abs(a0) < 1e-12 or abs(a0 - a1) > 1e-8 * scale or abs(a3) > 1e-8 * scale:
        return None
    center = (-a4 / a0, -a5 / a0)
    radius_squared = center[0] ** 2 + center[1] ** 2 - a2 / a0
    if radius_squared <= 0:
        return None
    return center, math.sqrt(radius_squared)


def _circle_obstacles(objects: list[GgbObject]) -> list[tuple[tuple[float, float], float]]:
    circles: list[tuple[tuple[float, float], float]] = []
    for obj in objects:
        if obj.visible and obj.kind in _CONIC_KINDS:
            circle = _circle_from_matrix(obj.attrs.get("matrix", {}))
            if circle:
                circles.append(circle)
    return circles


def _compact_canvas_bounds(
    objects: list[GgbObject],
    points: dict[str, tuple[float, float]],
    circles: list[tuple[tuple[float, float], float]],
    fallback: Viewport,
) -> tuple[tuple[float, float], tuple[float, float]]:
    coordinates = [
        points[obj.name]
        for obj in objects
        if obj.kind == "point" and obj.visible and obj.name in points
    ]
    x_values = [point[0] for point in coordinates]
    y_values = [point[1] for point in coordinates]
    for center, radius in circles:
        x_values.extend([center[0] - radius, center[0] + radius])
        y_values.extend([center[1] - radius, center[1] + radius])
    if not x_values or not y_values:
        return (fallback.x_min, fallback.y_min), (fallback.x_max, fallback.y_max)

    x_min, x_max = min(x_values), max(x_values)
    y_min, y_max = min(y_values), max(y_values)
    width = x_max - x_min
    height = y_max - y_min
    if width < 1e-9 and height < 1e-9:
        width = height = 2.0
        x_min -= 1.0
        x_max += 1.0
        y_min -= 1.0
        y_max += 1.0
    elif width < 1e-9:
        width = 0.6 * height
        center = (x_min + x_max) / 2
        x_min, x_max = center - width / 2, center + width / 2
    elif height < 1e-9:
        height = width / 1.8
        center = (y_min + y_max) / 2
        y_min, y_max = center - height / 2, center + height / 2

    ratio = width / height
    if ratio > 1.8:
        target_height = width / 1.8
        center = (y_min + y_max) / 2
        y_min, y_max = center - target_height / 2, center + target_height / 2
        height = target_height
    elif ratio < 0.6:
        target_width = 0.6 * height
        center = (x_min + x_max) / 2
        x_min, x_max = center - target_width / 2, center + target_width / 2
        width = target_width

    padding = 0.08 * max(width, height)
    return (
        (x_min - padding, y_min - padding),
        (x_max + padding, y_max + padding),
    )


def _normalized_positive_angle(angle: float) -> float:
    result = angle % (2 * math.pi)
    return result + 2 * math.pi if result < 0 else result


def _circumcenter(
    first: tuple[float, float],
    second: tuple[float, float],
    third: tuple[float, float],
) -> tuple[float, float] | None:
    ax, ay = first
    bx, by = second
    cx, cy = third
    determinant = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(determinant) < 1e-12:
        return None
    ux = (
        (ax * ax + ay * ay) * (by - cy)
        + (bx * bx + by * by) * (cy - ay)
        + (cx * cx + cy * cy) * (ay - by)
    ) / determinant
    uy = (
        (ax * ax + ay * ay) * (cx - bx)
        + (bx * bx + by * by) * (ax - cx)
        + (cx * cx + cy * cy) * (bx - ax)
    ) / determinant
    return ux, uy


def _arc_geometry(obj: GgbObject, points: dict[str, tuple[float, float]]):
    command = str(obj.attrs.get("command", "")).lower()
    inputs = list(obj.attrs.get("inputs", []))
    if command in {"circlearc", "circlesector"} and len(inputs) >= 3 and all(name in points for name in inputs[:3]):
        center = points[inputs[0]]
        start = points[inputs[1]]
        middle = None
        end = points[inputs[2]]
    elif command in {"circumcirclearc", "circumcirclesector"} and len(inputs) >= 3 and all(name in points for name in inputs[:3]):
        start, middle, end = (points[name] for name in inputs[:3])
        center = _circumcenter(start, middle, end)
        if center is None:
            return None
    elif command == "semicircle" and len(inputs) >= 2 and all(name in points for name in inputs[:2]):
        start, end = (points[name] for name in inputs[:2])
        center = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
        middle = None
    else:
        return None

    radius = math.dist(center, start)
    start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
    end_angle = math.atan2(end[1] - center[1], end[0] - center[0])
    extent = _normalized_positive_angle(end_angle - start_angle)
    if middle is not None:
        middle_angle = _normalized_positive_angle(
            math.atan2(middle[1] - center[1], middle[0] - center[0]) - start_angle
        )
        if middle_angle > extent + 1e-9:
            extent = -_normalized_positive_angle(start_angle - end_angle)
    return center, radius, start_angle, extent, command.endswith("sector"), start, end


def _convert_function_expression(expression: str, label: str) -> str | None:
    value = expression.strip()
    if "=" in value:
        left, value = value.split("=", 1)
        if label not in left and "x" not in left:
            return None
    value = value.strip()
    replacements = {
        "π": "pi", "ℯ": "E", "√": "sqrt", "ln(": "log(",
        "arcsin(": "asin(", "arccos(": "acos(", "arctan(": "atan(",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    return re.sub(r"(\d)([A-Za-z(])", r"\1*\2", value)


@dataclass
class _Generator:
    parsed: ParsedGgb
    preserve_style: bool
    debug: bool

    def _visible_inputs(self, obj: GgbObject, points: dict[str, tuple[float, float]]) -> list[str]:
        return [name for name in obj.attrs.get("inputs", []) if name in points]

    def _point_usage(
        self,
        points: dict[str, tuple[float, float]],
        supports: list[tuple],
        view: Viewport,
    ) -> dict[str, int]:
        tolerance = max(view.x_max - view.x_min, view.y_max - view.y_min) * 1e-6
        counts: dict[str, int] = {}
        for name, point in points.items():
            distinct_lines = {
                (round(support[0], 7), round(support[1], 7), round(support[2], 6))
                for support in supports
                if _point_on_support(point, support, tolerance)
            }
            counts[name] = len(distinct_lines)
        return counts

    def _label_layout(
        self,
        objects: list[GgbObject],
        points: dict[str, tuple[float, float]],
        supports: list[tuple],
        view: Viewport,
        counts: dict[str, int],
        circles: list[tuple[tuple[float, float], float]],
    ) -> dict[str, str]:
        direction_vectors = {
            "E": (1.0, 0.0), "NE": (math.sqrt(0.5), math.sqrt(0.5)),
            "N": (0.0, 1.0), "NW": (-math.sqrt(0.5), math.sqrt(0.5)),
            "W": (-1.0, 0.0), "SW": (-math.sqrt(0.5), -math.sqrt(0.5)),
            "S": (0.0, -1.0), "SE": (math.sqrt(0.5), -math.sqrt(0.5)),
        }
        labeled_names = [
            obj.name for obj in objects
            if obj.kind == "point" and obj.visible and obj.label_visible and obj.name in points
        ]
        if not labeled_names:
            return {}
        scale = max(view.x_max - view.x_min, view.y_max - view.y_min, 1.0)
        point_cloud = [points[name] for name in labeled_names]
        point_objects = {obj.name: obj for obj in objects if obj.kind == "point"}
        conic_matrices = [
            obj.attrs.get("matrix", {})
            for obj in objects
            if obj.visible and obj.kind in _CONIC_KINDS and obj.attrs.get("matrix")
        ]
        layouts: dict[str, str] = {}
        chosen_anchors: list[tuple[float, float]] = []

        def nearest_distance(name: str) -> float:
            others = [math.dist(points[name], points[other]) for other in labeled_names if other != name]
            return min(others, default=scale)

        ordered_names = sorted(
            labeled_names,
            key=lambda name: (counts.get(name, 0), -nearest_distance(name)),
            reverse=True,
        )
        for name in ordered_names:
            point = points[name]
            manual_offset = point_objects[name].attrs.get("label_offset", {})
            if "x" in manual_offset or "y" in manual_offset:
                manual_vector = (
                    float(manual_offset.get("x", 0.0)),
                    -float(manual_offset.get("y", 0.0)),
                )
                if math.hypot(*manual_vector) > 1e-9:
                    best_direction = max(
                        direction_vectors,
                        key=lambda direction: (
                            direction_vectors[direction][0] * manual_vector[0]
                            + direction_vectors[direction][1] * manual_vector[1]
                        ),
                    )
                    magnitude = math.hypot(*manual_vector)
                    factor = 1.5 if magnitude >= 24 else 1.25 if magnitude >= 14 else 1.0
                    layouts[name] = f"{factor:g}*{best_direction}" if factor > 1 else best_direction
                    vector = direction_vectors[best_direction]
                    chosen_anchors.append((
                        point[0] + 0.032 * scale * factor * vector[0],
                        point[1] + 0.032 * scale * factor * vector[1],
                    ))
                    continue

            tangent_supports = _conic_tangent_supports(point, conic_matrices, scale)
            nearest = nearest_distance(name)
            crowd_factor = 1.5 if nearest < 0.025 * scale else 1.25 if nearest < 0.05 * scale else 1.0
            offset = 0.036 * scale * crowd_factor
            nearest_points = sorted(
                (other for other in labeled_names if other != name),
                key=lambda other: math.dist(point, points[other]),
            )[:4]
            if nearest_points:
                centroid = (
                    sum(points[other][0] for other in nearest_points) / len(nearest_points),
                    sum(points[other][1] for other in nearest_points) / len(nearest_points),
                )
                outward = (point[0] - centroid[0], point[1] - centroid[1])
            else:
                outward = (0.0, 0.0)

            label_supports = [*supports, *tangent_supports]
            free_sector = _largest_free_sector_direction(point, label_supports, 1e-5 * scale)
            if free_sector:
                outward = (
                    outward[0] + 12.0 * free_sector[0],
                    outward[1] + 12.0 * free_sector[1],
                )

            radial_vectors: list[tuple[float, float]] = []
            for center, radius in circles:
                radial = (point[0] - center[0], point[1] - center[1])
                radial_length = math.hypot(*radial)
                if radial_length > 1e-12 and abs(radial_length - radius) < 0.005 * scale:
                    unit_radial = (radial[0] / radial_length, radial[1] / radial_length)
                    radial_vectors.append(unit_radial)
                    outward = (
                        outward[0] + 2.5 * unit_radial[0],
                        outward[1] + 2.5 * unit_radial[1],
                    )
            outward_norm = math.hypot(*outward)
            if outward_norm > 1e-12:
                outward = (outward[0] / outward_norm, outward[1] / outward_norm)

            best_direction = "NE"
            best_anchor = point
            best_score = float("inf")
            for direction, vector in direction_vectors.items():
                anchor = (point[0] + offset * vector[0], point[1] + offset * vector[1])
                score = -10.0 * (vector[0] * outward[0] + vector[1] * outward[1])
                for radial in radial_vectors:
                    radial_alignment = vector[0] * radial[0] + vector[1] * radial[1]
                    if radial_alignment < 0:
                        score += 18.0 * -radial_alignment
                    else:
                        score -= 3.0 * radial_alignment

                direction_penalty = 0.0
                nearby_line_penalty = 0.0
                for support in label_supports:
                    if _point_on_support(point, support, 1e-5 * scale):
                        normal_alignment = abs(support[0] * vector[0] + support[1] * vector[1])
                        direction_penalty += 3.5 * (1 - normal_alignment)
                    distance = _distance_to_support(anchor, support)
                    threshold = 0.035 * scale
                    if distance < threshold:
                        nearby_line_penalty += 3 * (threshold - distance) / threshold
                score += min(8.0, direction_penalty)
                score += min(7.0, nearby_line_penalty)
                conic_penalty = 0.0
                for matrix in conic_matrices:
                    distance_to_curve = _distance_to_conic(anchor, matrix)
                    threshold = 0.04 * scale
                    if distance_to_curve < threshold:
                        conic_penalty += 7 * (threshold - distance_to_curve) / threshold
                score += min(10.0, conic_penalty)
                circle_penalty = 0.0
                for center, radius in circles:
                    distance_to_curve = abs(math.dist(anchor, center) - radius)
                    threshold = 0.035 * scale
                    if distance_to_curve < threshold:
                        circle_penalty += 6 * (threshold - distance_to_curve) / threshold
                score += min(8.0, circle_penalty)

                for other_point in point_cloud:
                    if other_point == point:
                        continue
                    distance = math.dist(anchor, other_point)
                    threshold = 0.09 * scale
                    if distance < threshold:
                        score += 8 * (threshold - distance) / threshold
                for other_anchor in chosen_anchors:
                    distance = math.dist(anchor, other_anchor)
                    threshold = 0.10 * scale
                    if distance < threshold:
                        score += 14 * (threshold - distance) / threshold

                if score < best_score:
                    best_score = score
                    best_direction = direction
                    best_anchor = anchor

            chosen_anchors.append(best_anchor)
            if crowd_factor >= 1.5:
                layouts[name] = f"1.5*{best_direction}"
            elif crowd_factor > 1:
                layouts[name] = f"1.25*{best_direction}"
            else:
                layouts[name] = best_direction
        return layouts

    def build(self) -> AsyResult:
        objects = self.parsed.objects
        warnings = list(self.parsed.warnings)
        name_map = _NameMap([obj.name for obj in objects])
        points = {
            obj.name: coords
            for obj in objects
            if obj.kind == "point" and (coords := _point_coords(obj)) is not None
        }
        view = self.parsed.viewport
        circles = _circle_obstacles(objects)
        canvas_min, canvas_max = _compact_canvas_bounds(objects, points, circles, view)
        drawing_scale = max(canvas_max[0] - canvas_min[0], canvas_max[1] - canvas_min[1])
        layout_view = Viewport(
            x_min=canvas_min[0], x_max=canvas_max[0],
            y_min=canvas_min[1], y_max=canvas_max[1],
            axes_visible=view.axes_visible, grid_visible=view.grid_visible,
        )
        supports = _line_supports(objects, points)
        counts = self._point_usage(points, supports, layout_view)
        label_layout = self._label_layout(
            objects, points, supports, layout_view, counts, circles
        )

        required_points = {
            obj.name for obj in objects
            if obj.kind == "point" and obj.visible and obj.name in points
        }
        for obj in objects:
            if obj.visible:
                required_points.update(self._visible_inputs(obj, points))

        visible_conics = [obj for obj in objects if obj.visible and obj.kind in _CONIC_KINDS]
        needs_contour = any(
            obj.kind != "conicpart" and _circle_from_matrix(obj.attrs.get("matrix", {})) is None
            for obj in visible_conics
        )
        has_angle_marks = any(
            obj.visible and obj.kind == "angle" and len(self._visible_inputs(obj, points)) >= 3
            for obj in objects
        )

        body = [
            'usepackage("amsmath");',
            'size(8cm, keepAspect=true);',
            'import graph;',
            'import geometry;',
            'import olympiad;',
        ]
        if needs_contour:
            body.append('import contour;')
        body.extend([
            '',
            'pen thinline = linewidth(0.5);',
            'pen axispen = linewidth(0.2);',
            'pen dotpen = linewidth(1) + black;',
            'defaultpen(fontsize(8));',
            '',
        ])
        if self.debug:
            body.extend([
                f'// source XML: {_escape_asy_string(self.parsed.xml_name)}',
                f'// parsed objects: {len(objects)}',
                '',
            ])

        for obj in objects:
            if obj.kind == "point" and obj.name in required_points:
                body.append(f'pair {name_map.get(obj.name)} = {_pair_literal(points[obj.name])};')

        functions: list[str] = []
        drawings: list[str] = []
        angle_drawings: list[str] = []

        for obj in objects:
            if not obj.visible or obj.kind == "point":
                continue
            pen = _rgb_pen(obj, self.preserve_style)
            inputs = list(obj.attrs.get("inputs", []))

            if obj.kind == "segment":
                endpoints = _segment_inputs(obj)
                if endpoints and all(name in points for name in endpoints):
                    drawings.append(f'draw({name_map.get(endpoints[0])}--{name_map.get(endpoints[1])}, {pen});')
                else:
                    warnings.append(f'Skipped segment {obj.name}: endpoints are unavailable.')
            elif obj.kind == "line":
                coords = obj.attrs.get("coords", {})
                clipped = []
                if all(key in coords for key in ("x", "y", "z")):
                    clipped = _line_box_intersections(coords["x"], coords["y"], coords["z"], view)
                elif len(inputs) >= 2 and all(name in points for name in inputs[:2]):
                    clipped = _line_through_points(points[inputs[0]], points[inputs[1]], view)
                if len(clipped) == 2:
                    drawings.append(f'draw({_pair_literal(clipped[0])}--{_pair_literal(clipped[1])}, {pen});')
                else:
                    warnings.append(f'Skipped line {obj.name}: it does not cross the viewport.')
            elif obj.kind == "ray":
                if len(inputs) >= 2 and all(name in points for name in inputs[:2]):
                    start, through = points[inputs[0]], points[inputs[1]]
                    clipped = _line_through_points(start, through, view)
                    direction = (through[0] - start[0], through[1] - start[1])
                    forward = [
                        point for point in clipped
                        if (point[0] - start[0]) * direction[0] + (point[1] - start[1]) * direction[1] > 1e-9
                    ]
                    end = max(forward, key=lambda point: math.dist(start, point), default=through)
                    drawings.append(f'draw({name_map.get(inputs[0])}--{_pair_literal(end)}, {pen});')
                else:
                    warnings.append(f'Skipped ray {obj.name}: defining points are unavailable.')
            elif obj.kind == "vector":
                if len(inputs) >= 2 and all(name in points for name in inputs[:2]):
                    drawings.append(f'draw({name_map.get(inputs[0])}--{name_map.get(inputs[1])}, {pen}, Arrow(3));')
                elif len(inputs) == 1 and inputs[0] in points:
                    drawings.append(f'draw((0, 0)--{name_map.get(inputs[0])}, {pen}, Arrow(3));')
                else:
                    warnings.append(f'Skipped vector {obj.name}: defining points are unavailable.')
            elif obj.kind in {"polygon", "polyline"}:
                vertices = [name_map.get(name) for name in inputs if name in points]
                if len(vertices) >= (3 if obj.kind == "polygon" else 2):
                    ending = "--cycle" if obj.kind == "polygon" else ""
                    drawings.append(f'draw({"--".join(vertices)}{ending}, {pen});')
                else:
                    warnings.append(f'Skipped {obj.kind} {obj.name}: vertices are unavailable.')
            elif obj.kind == "conicpart":
                arc = _arc_geometry(obj, points)
                if arc:
                    center, radius, start_angle, extent, sector, arc_start, arc_end = arc
                    function_name = f'arc{name_map.get(obj.name)}'
                    functions.append(
                        f'pair {function_name}(real t) {{ return {_pair_literal(center)} + '
                        f'{_format_float(radius)}*(cos({_format_float(start_angle)} + t*{_format_float(extent)}), '
                        f'sin({_format_float(start_angle)} + t*{_format_float(extent)})); }}'
                    )
                    drawings.append(f'draw(graph({function_name}, 0, 1, n=120), {pen});')
                    if sector:
                        drawings.append(
                            f'draw({_pair_literal(center)}--{_pair_literal(arc_start)}^^'
                            f'{_pair_literal(center)}--{_pair_literal(arc_end)}, {pen});'
                        )
                else:
                    warnings.append(f'Skipped conic part {obj.name}: its arc definition is unsupported.')
            elif obj.kind in _CONIC_KINDS:
                matrix = obj.attrs.get("matrix", {})
                circle = _circle_from_matrix(matrix)
                expression = _conic_expression(matrix)
                circle_inputs = [name for name in inputs if name in points]
                if circle and str(obj.attrs.get("command", "")).lower() == "circle" and len(circle_inputs) >= 2:
                    if len(circle_inputs) >= 3:
                        args = ', '.join(name_map.get(name) for name in circle_inputs[:3])
                        drawings.append(f'draw(circle({args}), {pen});')
                    else:
                        center_name, point_name = circle_inputs[:2]
                        drawings.append(
                            f'draw(circle({name_map.get(center_name)}, abs({name_map.get(point_name)}-{name_map.get(center_name)})), {pen});'
                        )
                elif circle:
                    center, radius = circle
                    drawings.append(f'draw(circle({_pair_literal(center)}, {_format_float(radius)}), {pen});')
                elif expression:
                    function_name = f'conic{name_map.get(obj.name)}'
                    functions.append(f'real {function_name}(real x, real y) {{ return {expression}; }}')
                    drawings.append(
                        f'draw(contour({function_name}, {_pair_literal((view.x_min, view.y_min))}, '
                        f'{_pair_literal((view.x_max, view.y_max))}, new real[] {{0}}, 120), {pen});'
                    )
                else:
                    warnings.append(f'Skipped conic {obj.name}: matrix coefficients are unavailable.')
            elif obj.kind == "function":
                expression = _convert_function_expression(str(obj.attrs.get("expression", "")), obj.name)
                if expression:
                    function_name = f'f{name_map.get(obj.name)}'
                    functions.append(f'real {function_name}(real x) {{ return {expression}; }}')
                    drawings.append(
                        f'draw(graph({function_name}, {_format_float(view.x_min)}, {_format_float(view.x_max)}, n=500), {pen});'
                    )
                else:
                    warnings.append(f'Skipped function {obj.name}: expression is unavailable.')
            elif obj.kind == "angle":
                angle = _acute_anglemark(
                    self._visible_inputs(obj, points), points, name_map, 0.03 * drawing_scale
                )
                if angle:
                    angle_drawings.append(angle)
            elif self.debug and obj.kind not in {"numeric", "text", "boolean"}:
                drawings.append(f'// unsupported visible object: {obj.kind} {obj.name}')

        if functions:
            body.extend(['', *functions])

        point_lines: list[str] = []
        for obj in objects:
            if obj.kind != "point" or not obj.visible or obj.name not in points:
                continue
            identifier = name_map.get(obj.name)
            if obj.label_visible:
                direction = label_layout.get(obj.name, "NE")
                line = f'label("${_escape_tex(obj.name)}$", {identifier}, {direction});'
            else:
                line = ''
            if counts.get(obj.name, 0) < 2:
                line += f'dot({identifier}, {_rgb_pen(obj, self.preserve_style, point=True)});'
            if line:
                point_lines.append(line)

        body.extend([
            '',
            '// 画布范围',
            f'draw(box({_pair_literal(canvas_min)}, {_pair_literal(canvas_max)}), invisible);',
        ])

        if view.grid_visible:
            body.extend(['', '// 网格'])
            x_start, x_end = math.ceil(view.x_min), math.floor(view.x_max)
            y_start, y_end = math.ceil(view.y_min), math.floor(view.y_max)
            if x_end - x_start <= 100 and y_end - y_start <= 100:
                for x_value in range(x_start, x_end + 1):
                    body.append(
                        f'draw(({x_value}, {_format_float(view.y_min)})--({x_value}, {_format_float(view.y_max)}), gray(0.9)+axispen);'
                    )
                for y_value in range(y_start, y_end + 1):
                    body.append(
                        f'draw(({_format_float(view.x_min)}, {y_value})--({_format_float(view.x_max)}, {y_value}), gray(0.9)+axispen);'
                    )
            else:
                warnings.append('Skipped grid: the viewport contains more than 100 grid lines per axis.')

        if drawings:
            body.extend(['', '// 曲线与直线', *drawings])

        if view.axes_visible:
            body.extend([
                '',
                '// 坐标轴',
                f'draw(({_format_float(view.x_min)}, 0)--({_format_float(view.x_max)}, 0), axispen, Arrow(3));',
                f'draw((0, {_format_float(view.y_min)})--(0, {_format_float(view.y_max)}), axispen, Arrow(3));',
                f'label("$x$", ({_format_float(view.x_max)}, 0), E);',
                f'label("$y$", (0, {_format_float(view.y_max)}), N);',
            ])

        if has_angle_marks and angle_drawings:
            body.extend(['', '// 锐角标记', *angle_drawings])

        if point_lines:
            body.extend(['', '// 点与标签', *point_lines])

        body.extend([
            '',
            f'clip(box({_pair_literal(canvas_min)}, {_pair_literal(canvas_max)}));',
        ])
        if self.debug and warnings:
            body.extend(['', *[f'// warning: {warning}' for warning in warnings]])

        return AsyResult('\n'.join(body).rstrip() + '\n', objects, warnings)

def convert_ggb_to_asy(
    input_path: str | Path,
    output_path: str | Path | None = None,
    *,
    preserve_style: bool = False,
    debug: bool = False,
) -> AsyResult:
    parsed = parse_ggb(input_path)
    result = _Generator(parsed, preserve_style=preserve_style, debug=debug).build()
    if output_path is not None:
        Path(output_path).write_text(result.code, encoding="utf-8")
    return result































