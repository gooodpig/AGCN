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
            default_blue = color == (21, 101, 192)
            return (
                f"{_color_pen(color)}+dotpen"
                if not default_blue and not _is_neutral_color(color)
                else "dotpen"
            )
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


def _anglemark_from_vectors(
    vertex: tuple[float, float],
    first_vector: tuple[float, float],
    second_vector: tuple[float, float],
    radius: float,
    vertex_expression: str | None = None,
) -> str | None:
    if math.hypot(*first_vector) < 1e-12 or math.hypot(*second_vector) < 1e-12:
        return None
    if first_vector[0] * second_vector[0] + first_vector[1] * second_vector[1] < 0:
        first_vector = (-first_vector[0], -first_vector[1])
    cross = first_vector[0] * second_vector[1] - first_vector[1] * second_vector[0]
    if abs(cross) < 1e-12:
        return None
    if cross < 0:
        first_vector, second_vector = second_vector, first_vector
    start_angle = math.degrees(math.atan2(first_vector[1], first_vector[0]))
    end_angle = math.degrees(math.atan2(second_vector[1], second_vector[0]))
    while end_angle <= start_angle:
        end_angle += 360
    center = vertex_expression or _pair_literal(vertex)
    return (
        f"draw(arc({center}, {_format_float(radius)}, "
        f"{_format_float(start_angle)}, {_format_float(end_angle)}), thinline);"
    )


def _line_geometry(
    name: str,
    objects_by_name: dict[str, GgbObject],
    points: dict[str, tuple[float, float]],
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    if name == "xAxis":
        return (0.0, 0.0), (1.0, 0.0)
    if name == "yAxis":
        return (0.0, 0.0), (0.0, 1.0)
    obj = objects_by_name.get(name)
    if obj is None:
        return None
    inputs = [item for item in obj.attrs.get("inputs", []) if item in points]
    if len(inputs) >= 2:
        first, second = points[inputs[0]], points[inputs[1]]
        return first, (second[0] - first[0], second[1] - first[1])
    coords = obj.attrs.get("coords", {})
    if all(key in coords for key in ("x", "y", "z")):
        a, b, c = coords["x"], coords["y"], coords["z"]
        if abs(a) > abs(b) and abs(a) > 1e-12:
            point = (-c / a, 0.0)
        elif abs(b) > 1e-12:
            point = (0.0, -c / b)
        else:
            return None
        return point, (b, -a)
    return None


def _line_anglemark(
    names: list[str],
    objects_by_name: dict[str, GgbObject],
    points: dict[str, tuple[float, float]],
    radius: float,
) -> str | None:
    if len(names) < 2:
        return None
    first = _line_geometry(names[0], objects_by_name, points)
    second = _line_geometry(names[1], objects_by_name, points)
    if first is None or second is None:
        return None
    first_point, first_vector = first
    second_point, second_vector = second
    denominator = (
        first_vector[0] * second_vector[1]
        - first_vector[1] * second_vector[0]
    )
    if abs(denominator) < 1e-12:
        return None
    offset = (second_point[0] - first_point[0], second_point[1] - first_point[1])
    parameter = (
        offset[0] * second_vector[1] - offset[1] * second_vector[0]
    ) / denominator
    vertex = (
        first_point[0] + parameter * first_vector[0],
        first_point[1] + parameter * first_vector[1],
    )
    return _anglemark_from_vectors(vertex, first_vector, second_vector, radius)


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


def _implicit_polynomial_expression(coefficients: list[list[float]]) -> str | None:
    values = [value for row in coefficients for value in row]
    maximum = max((abs(value) for value in values), default=0.0)
    if maximum < 1e-15:
        return None

    terms: list[tuple[int, int, float]] = []
    for x_power, row in enumerate(coefficients):
        for y_power, value in enumerate(row):
            normalized = value / maximum
            if abs(normalized) > 1e-12:
                terms.append((x_power, y_power, normalized))
    terms.sort(key=lambda item: (item[0] + item[1], item[0]), reverse=True)

    rendered: list[str] = []
    for x_power, y_power, coefficient in terms:
        factors: list[str] = []
        if x_power:
            factors.append("x" if x_power == 1 else f"x^{x_power}")
        if y_power:
            factors.append("y" if y_power == 1 else f"y^{y_power}")
        magnitude = abs(coefficient)
        if factors and abs(magnitude - 1.0) < 1e-12:
            term = "*".join(factors)
        else:
            term = "*".join([_format_float(magnitude), *factors])
        if not rendered:
            rendered.append(f"-{term}" if coefficient < 0 else term)
        else:
            rendered.append(("-" if coefficient < 0 else "+") + term)
    return "".join(rendered) or None


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

def _implicit_polynomial_value_gradient(
    coefficients: list[list[float]],
    point: tuple[float, float],
) -> tuple[float, float, float] | None:
    if not coefficients:
        return None
    x, y = point
    value = 0.0
    gradient_x = 0.0
    gradient_y = 0.0
    for x_power, row in enumerate(coefficients):
        for y_power, coefficient in enumerate(row):
            value += coefficient * x ** x_power * y ** y_power
            if x_power:
                gradient_x += (
                    x_power * coefficient * x ** (x_power - 1) * y ** y_power
                )
            if y_power:
                gradient_y += (
                    y_power * coefficient * x ** x_power * y ** (y_power - 1)
                )
    return value, gradient_x, gradient_y


def _implicit_polynomial_tangent_supports(
    point: tuple[float, float],
    polynomials: list[list[list[float]]],
    scale: float,
) -> list[tuple]:
    supports: list[tuple] = []
    for coefficients in polynomials:
        evaluated = _implicit_polynomial_value_gradient(coefficients, point)
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


def _distance_to_implicit_polynomial(
    point: tuple[float, float],
    coefficients: list[list[float]],
) -> float:
    evaluated = _implicit_polynomial_value_gradient(coefficients, point)
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
    if fallback.axes_visible:
        x_padding = 0.05 * (fallback.x_max - fallback.x_min)
        y_padding = 0.05 * (fallback.y_max - fallback.y_min)
        return (
            (fallback.x_min - x_padding, fallback.y_min - y_padding),
            (fallback.x_max + x_padding, fallback.y_max + y_padding),
        )

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
    if command == "semicircle":
        extent = -math.pi
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
        objects: list[GgbObject],
        points: dict[str, tuple[float, float]],
        supports: list[tuple],
        view: Viewport,
    ) -> dict[str, int]:
        scale = max(view.x_max - view.x_min, view.y_max - view.y_min)
        tolerance = scale * 1e-5
        visible_curves = [
            obj for obj in objects if obj.visible and obj.kind in _CONIC_KINDS
        ]
        counts: dict[str, int] = {}
        for name, point in points.items():
            distinct_geometries: set[tuple] = {
                ("line", round(support[0], 7), round(support[1], 7), round(support[2], 6))
                for support in supports
                if _point_on_support(point, support, tolerance)
            }
            for obj in visible_curves:
                matrix = obj.attrs.get("matrix", {})
                coefficients = obj.attrs.get("coefficients", [])
                distance = (
                    _distance_to_implicit_polynomial(point, coefficients)
                    if coefficients
                    else _distance_to_conic(point, matrix)
                )
                if distance <= tolerance:
                    distinct_geometries.add(("curve", obj.name))
            counts[name] = len(distinct_geometries)
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
            "E": (1.0, 0.0),
            "NE": (math.sqrt(0.5), math.sqrt(0.5)),
            "N": (0.0, 1.0),
            "NW": (-math.sqrt(0.5), math.sqrt(0.5)),
            "W": (-1.0, 0.0),
            "SW": (-math.sqrt(0.5), -math.sqrt(0.5)),
            "S": (0.0, -1.0),
            "SE": (math.sqrt(0.5), -math.sqrt(0.5)),
        }
        point_objects = {
            obj.name: obj
            for obj in objects
            if obj.kind == "point" and obj.visible and obj.name in points
        }
        labeled_names = [
            name for name, obj in point_objects.items() if obj.label_visible
        ]
        if not labeled_names:
            return {}

        scale = max(view.x_max - view.x_min, view.y_max - view.y_min, 1.0)
        point_cloud = list(points.values())
        scoring_supports: list[tuple] = []
        support_keys: set[tuple] = set()
        for support in supports:
            a, b, c, first, second, mode = support
            if mode == "line":
                key = (mode, round(a, 7), round(b, 7), round(c, 7))
            else:
                endpoints = (
                    tuple(round(value, 7) for value in first),
                    tuple(round(value, 7) for value in second),
                )
                if mode == "segment":
                    endpoints = tuple(sorted(endpoints))
                key = (mode, *endpoints)
            if key not in support_keys:
                support_keys.add(key)
                scoring_supports.append(support)
        conic_matrices = [
            matrix
            for obj in objects
            if obj.visible and obj.kind in _CONIC_KINDS
            if (matrix := obj.attrs.get("matrix", {}))
            if _circle_from_matrix(matrix) is None
        ]
        implicit_polynomials = [
            coefficients
            for obj in objects
            if obj.visible and obj.kind == "implicitpoly"
            if (coefficients := obj.attrs.get("coefficients", []))
        ]
        box_margin = 0.007 * scale

        def nearest_distance(name: str) -> float:
            return min(
                (
                    math.dist(points[name], points[other])
                    for other in labeled_names
                    if other != name
                ),
                default=scale,
            )

        def local_density(name: str) -> int:
            return sum(
                math.dist(points[name], points[other]) < 0.14 * scale
                for other in labeled_names
                if other != name
            )

        def label_dimensions(name: str) -> tuple[float, float]:
            base_name = name.replace("'", "")
            visible_length = max(1.0, len(base_name) + 0.55 * name.count("'"))
            return (
                (0.018 + 0.012 * visible_length) * scale,
                0.032 * scale,
            )

        def candidate_geometry(
            point: tuple[float, float],
            vector: tuple[float, float],
            factor: float,
            width: float,
            height: float,
        ) -> tuple[tuple[float, float], tuple[float, float, float, float]]:
            projected_extent = (
                abs(vector[0]) * width / 2 + abs(vector[1]) * height / 2
            )
            distance = projected_extent + factor * 0.010 * scale
            center = (
                point[0] + distance * vector[0],
                point[1] + distance * vector[1],
            )
            return center, (
                center[0] - width / 2,
                center[1] - height / 2,
                center[0] + width / 2,
                center[1] + height / 2,
            )

        def distance_to_box(
            point: tuple[float, float],
            box: tuple[float, float, float, float],
        ) -> float:
            delta_x = max(box[0] - point[0], 0.0, point[0] - box[2])
            delta_y = max(box[1] - point[1], 0.0, point[1] - box[3])
            return math.hypot(delta_x, delta_y)

        def box_overlap(
            first: tuple[float, float, float, float],
            second: tuple[float, float, float, float],
        ) -> tuple[float, float]:
            return (
                max(0.0, min(first[2], second[2]) - max(first[0], second[0])),
                max(0.0, min(first[3], second[3]) - max(first[1], second[1])),
            )

        def box_gap(
            first: tuple[float, float, float, float],
            second: tuple[float, float, float, float],
        ) -> float:
            gap_x = max(second[0] - first[2], first[0] - second[2], 0.0)
            gap_y = max(second[1] - first[3], first[1] - second[3], 0.0)
            return math.hypot(gap_x, gap_y)

        def pair_cost(
            first: dict,
            second: dict,
        ) -> float:
            overlap_x, overlap_y = box_overlap(first["box"], second["box"])
            if overlap_x > 0 and overlap_y > 0:
                first_area = first["width"] * first["height"]
                second_area = second["width"] * second["height"]
                overlap_ratio = overlap_x * overlap_y / max(
                    1e-12, min(first_area, second_area)
                )
                return 2400.0 + 1400.0 * overlap_ratio
            gap = box_gap(first["box"], second["box"])
            if gap < box_margin:
                return 90.0 * (box_margin - gap) / box_margin
            return 0.0

        def preferred_vectors(name: str) -> tuple[tuple[float, float], tuple[float, float] | None]:
            point = points[name]
            nearest_names = sorted(
                (other for other in labeled_names if other != name),
                key=lambda other: math.dist(point, points[other]),
            )[:5]
            if nearest_names:
                centroid = (
                    sum(points[other][0] for other in nearest_names) / len(nearest_names),
                    sum(points[other][1] for other in nearest_names) / len(nearest_names),
                )
                outward = (point[0] - centroid[0], point[1] - centroid[1])
            else:
                outward = (0.0, 0.0)
            outward_length = math.hypot(*outward)
            if outward_length > 1e-12:
                outward = (outward[0] / outward_length, outward[1] / outward_length)

            tangent_supports = [
                *_conic_tangent_supports(point, conic_matrices, scale),
                *_implicit_polynomial_tangent_supports(
                    point, implicit_polynomials, scale
                ),
            ]
            free_sector = _largest_free_sector_direction(
                point, [*scoring_supports, *tangent_supports], 1e-5 * scale
            )
            return outward, free_sector

        def static_cost(
            name: str,
            vector: tuple[float, float],
            factor: float,
            center: tuple[float, float],
            box: tuple[float, float, float, float],
            width: float,
            height: float,
            outward: tuple[float, float],
            free_sector: tuple[float, float] | None,
            radial_vectors: list[tuple[float, float]],
            label_supports: list[tuple],
        ) -> float:
            score = 3.0 * (min(factor, 1.5) - 1.0)
            score += 120.0 * max(0.0, factor - 1.5)
            score -= 3.0 * (vector[0] * outward[0] + vector[1] * outward[1])
            if free_sector is not None:
                score -= 5.0 * (
                    vector[0] * free_sector[0] + vector[1] * free_sector[1]
                )

            for radial in radial_vectors:
                alignment = vector[0] * radial[0] + vector[1] * radial[1]
                if alignment < 0:
                    score += (14.0 if counts.get(name, 0) < 2 else 2.0) * -alignment
                else:
                    score -= 1.5 * alignment

            for support in label_supports:
                if _point_on_support(points[name], support, 1e-5 * scale):
                    normal_alignment = abs(
                        support[0] * vector[0] + support[1] * vector[1]
                    )
                    score += 2.5 * (1.0 - normal_alignment)
                projected_radius = (
                    abs(support[0]) * width / 2
                    + abs(support[1]) * height / 2
                )
                clearance = _distance_to_support(center, support) - projected_radius
                threshold = 0.006 * scale
                if clearance <= 0:
                    score += 150.0 + 80.0 * min(1.0, -clearance / threshold)
                elif clearance < threshold:
                    score += 35.0 * (threshold - clearance) / threshold

            label_radius = math.hypot(width, height) / 2
            for matrix in conic_matrices:
                clearance = _distance_to_conic(center, matrix) - label_radius
                threshold = 0.006 * scale
                if clearance <= 0:
                    score += 130.0 + 60.0 * min(1.0, -clearance / threshold)
                elif clearance < threshold:
                    score += 30.0 * (threshold - clearance) / threshold

            for coefficients in implicit_polynomials:
                clearance = (
                    _distance_to_implicit_polynomial(center, coefficients)
                    - label_radius
                )
                threshold = 0.006 * scale
                if clearance <= 0:
                    score += 130.0 + 60.0 * min(1.0, -clearance / threshold)
                elif clearance < threshold:
                    score += 30.0 * (threshold - clearance) / threshold

            for circle_center, radius in circles:
                nearest = distance_to_box(circle_center, box)
                farthest = max(
                    math.dist(circle_center, corner)
                    for corner in (
                        (box[0], box[1]),
                        (box[0], box[3]),
                        (box[2], box[1]),
                        (box[2], box[3]),
                    )
                )
                threshold = 0.006 * scale
                if nearest <= radius <= farthest:
                    score += 150.0
                else:
                    clearance = min(abs(radius - nearest), abs(radius - farthest))
                    if clearance < threshold:
                        score += 30.0 * (threshold - clearance) / threshold

            for other_point in point_cloud:
                if math.dist(other_point, points[name]) < 1e-12:
                    continue
                clearance = distance_to_box(other_point, box)
                threshold = 0.010 * scale
                if clearance <= 1e-12:
                    score += 260.0
                elif clearance < threshold:
                    score += 55.0 * (threshold - clearance) / threshold

            overflow = (
                max(0.0, view.x_min - box[0])
                + max(0.0, box[2] - view.x_max)
                + max(0.0, view.y_min - box[1])
                + max(0.0, box[3] - view.y_max)
            )
            if overflow > 0:
                score += 900.0 + 900.0 * overflow / (0.02 * scale)
            return score

        candidates: dict[str, list[dict]] = {}
        for name in labeled_names:
            point = points[name]
            width, height = label_dimensions(name)
            manual_offset = point_objects[name].attrs.get("label_offset", {})
            outward, free_sector = preferred_vectors(name)
            tangent_supports = [
                *_conic_tangent_supports(point, conic_matrices, scale),
                *_implicit_polynomial_tangent_supports(
                    point, implicit_polynomials, scale
                ),
            ]
            label_supports = [*scoring_supports, *tangent_supports]
            radial_vectors: list[tuple[float, float]] = []
            for circle_center, radius in circles:
                radial = (point[0] - circle_center[0], point[1] - circle_center[1])
                radial_length = math.hypot(*radial)
                if radial_length > 1e-12 and abs(radial_length - radius) < 0.005 * scale:
                    radial_vectors.append(
                        (radial[0] / radial_length, radial[1] / radial_length)
                    )

            manual_preference: tuple[tuple[float, float], float] | None = None
            if "x" in manual_offset or "y" in manual_offset:
                manual_vector = (
                    float(manual_offset.get("x", 0.0)),
                    -float(manual_offset.get("y", 0.0)),
                )
                if math.hypot(*manual_vector) > 1e-9:
                    direction = max(
                        direction_vectors,
                        key=lambda candidate: (
                            direction_vectors[candidate][0] * manual_vector[0]
                            + direction_vectors[candidate][1] * manual_vector[1]
                        ),
                    )
                    magnitude = math.hypot(*manual_vector)
                    factor = 1.5 if magnitude >= 24 else 1.25 if magnitude >= 14 else 1.0
                    manual_preference = direction_vectors[direction], factor

            directions = [
                (direction, vector, factor)
                for factor in (1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0)
                for direction, vector in direction_vectors.items()
            ]

            name_candidates: list[dict] = []
            for direction, vector, factor in directions:
                center, box = candidate_geometry(point, vector, factor, width, height)
                cost = static_cost(
                    name,
                    vector,
                    factor,
                    center,
                    box,
                    width,
                    height,
                    outward,
                    free_sector,
                    radial_vectors,
                    label_supports,
                )
                if manual_preference is not None:
                    preferred_vector, preferred_factor = manual_preference
                    alignment = (
                        vector[0] * preferred_vector[0]
                        + vector[1] * preferred_vector[1]
                    )
                    cost += 14.0 * (1.0 - alignment)
                    cost += 3.0 * abs(factor - preferred_factor)
                name_candidates.append(
                    {
                        "direction": direction,
                        "factor": factor,
                        "center": center,
                        "box": box,
                        "width": width,
                        "height": height,
                        "cost": cost,
                    }
                )
            candidates[name] = name_candidates

        constrained_order = sorted(
            labeled_names,
            key=lambda name: (
                len(candidates[name]) == 1,
                counts.get(name, 0),
                local_density(name),
                -nearest_distance(name),
                len(name),
            ),
            reverse=True,
        )

        def assignment_cost(assignment: dict[str, int]) -> float:
            total = sum(
                candidates[name][index]["cost"]
                for name, index in assignment.items()
            )
            for position, first_name in enumerate(labeled_names):
                first = candidates[first_name][assignment[first_name]]
                for second_name in labeled_names[position + 1:]:
                    second = candidates[second_name][assignment[second_name]]
                    total += pair_cost(first, second)
            return total

        def candidate_cost(
            name: str,
            index: int,
            assignment: dict[str, int],
        ) -> float:
            candidate = candidates[name][index]
            return candidate["cost"] + sum(
                pair_cost(candidate, candidates[other][other_index])
                for other, other_index in assignment.items()
                if other != name
            )

        def greedy_assignment(order: list[str]) -> dict[str, int]:
            assignment: dict[str, int] = {}
            for name in order:
                assignment[name] = min(
                    range(len(candidates[name])),
                    key=lambda index: (
                        candidate_cost(name, index, assignment),
                        index,
                    ),
                )
            return assignment

        def optimize(assignment: dict[str, int], order: list[str]) -> dict[str, int]:
            for sweep in range(14):
                changed = False
                sweep_order = order if sweep % 2 == 0 else list(reversed(order))
                for name in sweep_order:
                    best_index = min(
                        range(len(candidates[name])),
                        key=lambda index: (
                            candidate_cost(name, index, assignment),
                            index,
                        ),
                    )
                    if best_index != assignment[name]:
                        assignment[name] = best_index
                        changed = True
                if not changed:
                    break
            return assignment

        seed_orders = [
            constrained_order,
            list(reversed(constrained_order)),
            labeled_names,
            list(reversed(labeled_names)),
        ]
        assignments = [
            optimize(greedy_assignment(order), constrained_order)
            for order in seed_orders
        ]
        independent = {
            name: min(
                range(len(candidates[name])),
                key=lambda index: (candidates[name][index]["cost"], index),
            )
            for name in labeled_names
        }
        assignments.append(optimize(independent, constrained_order))
        best_assignment = min(assignments, key=assignment_cost)

        layouts: dict[str, str] = {}
        for name in labeled_names:
            selected = candidates[name][best_assignment[name]]
            factor = selected["factor"]
            direction = selected["direction"]
            layouts[name] = f"{factor:g}*{direction}" if factor > 1 else direction
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
        counts = self._point_usage(objects, points, supports, layout_view)
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
            obj.visible and obj.kind == "angle" for obj in objects
        )
        objects_by_name = {obj.name: obj for obj in objects}

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
        function_names = {obj.name for obj in objects if obj.kind == "function"}

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
                coefficients = obj.attrs.get("coefficients", [])
                polynomial_expression = _implicit_polynomial_expression(coefficients)
                circle = _circle_from_matrix(matrix)
                expression = _conic_expression(matrix)
                circle_inputs = [name for name in inputs if name in points]
                if polynomial_expression:
                    function_name = f'curve{name_map.get(obj.name)}'
                    functions.append(
                        f'real {function_name}(real x, real y) {{ return {polynomial_expression}; }}'
                    )
                    drawings.append(
                        f'draw(contour({function_name}, {_pair_literal((view.x_min, view.y_min))}, '
                        f'{_pair_literal((view.x_max, view.y_max))}, new real[] {{0}}, 180), {pen});'
                    )
                elif circle and str(obj.attrs.get("command", "")).lower() == "circle" and len(circle_inputs) >= 2:
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
                    warnings.append(f'Skipped curve {obj.name}: coefficients are unavailable.')
            elif obj.kind == "function":
                function_name = f'f{name_map.get(obj.name)}'
                previous_name = obj.name[:-1] if obj.name.endswith("'") else ""
                if previous_name in function_names:
                    previous_function = f'f{name_map.get(previous_name)}'
                    functions.append(
                        f'real {function_name}(real x) {{ real h=1e-5*(1+abs(x)); '
                        f'return ({previous_function}(x+h)-{previous_function}(x-h))/(2*h); }}'
                    )
                    drawings.append(
                        f'draw(graph({function_name}, {_format_float(view.x_min)}, {_format_float(view.x_max)}, n=500), {pen});'
                    )
                else:
                    expression = _convert_function_expression(
                        str(obj.attrs.get("expression", "")), obj.name
                    )
                    if expression:
                        functions.append(
                            f'real {function_name}(real x) {{ return {expression}; }}'
                        )
                        drawings.append(
                            f'draw(graph({function_name}, {_format_float(view.x_min)}, {_format_float(view.x_max)}, n=500), {pen});'
                        )
                    else:
                        warnings.append(
                            f'Skipped function {obj.name}: expression is unavailable.'
                        )
            elif obj.kind == "angle":
                raw_inputs = list(obj.attrs.get("inputs", []))
                angle = _acute_anglemark(
                    self._visible_inputs(obj, points), points, name_map, 0.03 * drawing_scale
                )
                if angle is None:
                    angle = _line_anglemark(
                        raw_inputs, objects_by_name, points, 0.03 * drawing_scale
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
