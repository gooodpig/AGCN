from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Callable

from .models import GgbObject


@dataclass(frozen=True)
class SymbolicPoint:
    code: str
    dependencies: frozenset[str] = frozenset()
    symbolic: bool = True
    needs_intersection_helper: bool = False


@dataclass(frozen=True)
class _LineGeometry:
    point: str
    direction: str
    dependencies: frozenset[str]

    @property
    def path(self) -> str:
        return (
            f"({self.point}-100*({self.direction})"
            f"--{self.point}+100*({self.direction}))"
        )


@dataclass(frozen=True)
class _PathGeometry:
    code: str
    dependencies: frozenset[str]


class SymbolicPointResolver:
    def __init__(
        self,
        objects: list[GgbObject],
        points: dict[str, tuple[float, float]],
        name_for: Callable[[str], str],
        pair_literal: Callable[[tuple[float, float]], str],
    ) -> None:
        self.objects = objects
        self.points = points
        self.name_for = name_for
        self.pair_literal = pair_literal
        self.objects_by_name = {obj.name: obj for obj in objects}
        self._cache: dict[str, SymbolicPoint] = {}

    def resolve(self, name: str) -> SymbolicPoint:
        if name in self._cache:
            return self._cache[name]
        obj = self.objects_by_name.get(name)
        fallback = SymbolicPoint(
            self.pair_literal(self.points[name]),
            symbolic=False,
        )
        if obj is None or obj.kind != "point":
            return fallback
        result = self._resolve_command(obj) or fallback
        self._cache[name] = result
        return result

    def dependency_closure(self, names: set[str]) -> set[str]:
        required = set(names)
        pending = list(names)
        while pending:
            name = pending.pop()
            if name not in self.points:
                continue
            for dependency in self.resolve(name).dependencies:
                if dependency in self.points and dependency not in required:
                    required.add(dependency)
                    pending.append(dependency)
        return required

    def declaration_order(self, names: set[str]) -> list[str]:
        ordered: list[str] = []
        complete: set[str] = set()
        active: set[str] = set()

        def visit(name: str) -> None:
            if name in complete or name not in names:
                return
            if name in active:
                return
            active.add(name)
            for dependency in self.resolve(name).dependencies:
                visit(dependency)
            active.remove(name)
            complete.add(name)
            ordered.append(name)

        for obj in self.objects:
            if obj.kind == "point" and obj.name in names:
                visit(obj.name)
        return ordered

    def _point(self, name: str) -> tuple[str, frozenset[str]] | None:
        if name not in self.points:
            return None
        return self.name_for(name), frozenset({name})

    def _numeric(self, name: str) -> str | None:
        obj = self.objects_by_name.get(name)
        if obj is None or obj.kind != "numeric":
            try:
                return str(float(name))
            except ValueError:
                return None
        value = obj.attrs.get("value")
        return None if value is None else f"{float(value):.12g}"

    @staticmethod
    def _object_endpoint_names(obj: GgbObject) -> tuple[str, str] | None:
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

    def _object_line_endpoints(
        self,
        obj: GgbObject,
    ) -> tuple[str, str, frozenset[str]] | None:
        endpoint_names = self._object_endpoint_names(obj)
        if endpoint_names:
            first = self._point(endpoint_names[0])
            second = self._point(endpoint_names[1])
            if first and second:
                return first[0], second[0], first[1] | second[1]
        return None

    def _line(self, name: str) -> _LineGeometry | None:
        if name == "xAxis":
            return _LineGeometry("(0,0)", "(1,0)", frozenset())
        if name == "yAxis":
            return _LineGeometry("(0,0)", "(0,1)", frozenset())
        inline = re.fullmatch(r"Line\[(.+?),\s*(.+?)\]", name, re.IGNORECASE)
        if inline:
            first = self._point(inline.group(1))
            second = self._point(inline.group(2))
            if first and second:
                return _LineGeometry(
                    first[0],
                    f"{second[0]}-{first[0]}",
                    first[1] | second[1],
                )
        obj = self.objects_by_name.get(name)
        if obj is None:
            return None
        inputs = list(obj.attrs.get("inputs", []))
        command = str(obj.attrs.get("command", "")).lower()

        special_line_commands = {
            "orthogonalline",
            "parallelline",
            "linebisector",
            "angularbisector",
            "anglebisector",
        }
        if (
            obj.kind in {"line", "segment", "ray", "vector"}
            and command not in special_line_commands
        ):
            endpoints = self._object_line_endpoints(obj)
            if endpoints:
                first, second, dependencies = endpoints
                return _LineGeometry(
                    first,
                    f"{second}-{first}",
                    dependencies,
                )

        if command in {"orthogonalline", "parallelline"} and len(inputs) >= 2:
            point = self._point(inputs[0])
            base = self._line(inputs[1])
            if point and base:
                direction = base.direction
                if command == "orthogonalline":
                    direction = f"rotate(90)*({direction})"
                return _LineGeometry(
                    point[0],
                    direction,
                    point[1] | base.dependencies,
                )

        if command == "linebisector":
            endpoints = self._line_endpoints(inputs)
            if endpoints:
                first, second, dependencies = endpoints
                return _LineGeometry(
                    f"({first}+{second})/2",
                    f"rotate(90)*({second}-{first})",
                    dependencies,
                )

        if command in {"angularbisector", "anglebisector"} and len(inputs) >= 3:
            refs = [self._point(item) for item in inputs[:3]]
            if all(refs):
                first, vertex, third = refs
                dependencies = first[1] | vertex[1] | third[1]
                return _LineGeometry(
                    vertex[0],
                    f"bisectorpoint({first[0]},{vertex[0]},{third[0]})-{vertex[0]}",
                    dependencies,
                )
        return None

    def _numeric_line(
        self,
        name: str,
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        if name == "xAxis":
            return (0.0, 0.0), (1.0, 0.0)
        if name == "yAxis":
            return (0.0, 0.0), (0.0, 1.0)
        inline = re.fullmatch(r"Line\[(.+?),\s*(.+?)\]", name, re.IGNORECASE)
        if inline:
            first = self.points.get(inline.group(1))
            second = self.points.get(inline.group(2))
            if first and second:
                return first, (second[0] - first[0], second[1] - first[1])
        obj = self.objects_by_name.get(name)
        if obj is None:
            return None
        inputs = list(obj.attrs.get("inputs", []))
        command = str(obj.attrs.get("command", "")).lower()
        special = {
            "orthogonalline",
            "parallelline",
            "linebisector",
            "angularbisector",
            "anglebisector",
        }
        if command not in special:
            endpoint_names = self._object_endpoint_names(obj)
            first = self.points.get(endpoint_names[0]) if endpoint_names else None
            second = self.points.get(endpoint_names[1]) if endpoint_names else None
            if first and second:
                return first, (second[0] - first[0], second[1] - first[1])
        if command in {"orthogonalline", "parallelline"} and len(inputs) >= 2:
            point = self.points.get(inputs[0])
            base = self._numeric_line(inputs[1])
            if point and base:
                direction = base[1]
                if command == "orthogonalline":
                    direction = (-direction[1], direction[0])
                return point, direction
        if command == "linebisector":
            endpoints = self._numeric_line_endpoints(inputs)
            if endpoints:
                first, second = endpoints
                return (
                    ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2),
                    (first[1] - second[1], second[0] - first[0]),
                )
        if command in {"angularbisector", "anglebisector"} and len(inputs) >= 3:
            first, vertex, third = (self.points.get(item) for item in inputs[:3])
            if first and vertex and third:
                first_vector = (first[0] - vertex[0], first[1] - vertex[1])
                third_vector = (third[0] - vertex[0], third[1] - vertex[1])
                first_length = math.hypot(*first_vector)
                third_length = math.hypot(*third_vector)
                if first_length > 1e-12 and third_length > 1e-12:
                    direction = (
                        first_vector[0] / first_length + third_vector[0] / third_length,
                        first_vector[1] / first_length + third_vector[1] / third_length,
                    )
                    return vertex, direction
        return None

    def _numeric_line_endpoints(
        self,
        inputs: list[str],
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        if len(inputs) >= 2:
            first = self.points.get(inputs[0])
            second = self.points.get(inputs[1])
            if first and second:
                return first, second
        if len(inputs) == 1:
            line = self.objects_by_name.get(inputs[0])
            if line is not None:
                endpoint_names = self._object_endpoint_names(line)
                if endpoint_names:
                    first = self.points.get(endpoint_names[0])
                    second = self.points.get(endpoint_names[1])
                    if first and second:
                        return first, second
        return None

    def _validated_line_intersection(
        self,
        first_name: str,
        second_name: str,
        expected: tuple[float, float],
    ) -> bool:
        first = self._numeric_line(first_name)
        second = self._numeric_line(second_name)
        if first is None or second is None:
            return False
        first_point, first_direction = first
        second_point, second_direction = second
        denominator = (
            first_direction[0] * second_direction[1]
            - first_direction[1] * second_direction[0]
        )
        direction_scale = math.hypot(*first_direction) * math.hypot(*second_direction)
        if direction_scale < 1e-12 or abs(denominator) < 1e-10 * direction_scale:
            return False
        offset = (
            second_point[0] - first_point[0],
            second_point[1] - first_point[1],
        )
        parameter = (
            offset[0] * second_direction[1] - offset[1] * second_direction[0]
        ) / denominator
        intersection = (
            first_point[0] + parameter * first_direction[0],
            first_point[1] + parameter * first_direction[1],
        )
        scale = max(1.0, math.hypot(*expected))
        return math.dist(intersection, expected) <= 1e-6 * scale

    def _line_endpoints(
        self,
        inputs: list[str],
    ) -> tuple[str, str, frozenset[str]] | None:
        if len(inputs) >= 2:
            first = self._point(inputs[0])
            second = self._point(inputs[1])
            if first and second:
                return first[0], second[0], first[1] | second[1]
        if len(inputs) == 1:
            line = self.objects_by_name.get(inputs[0])
            if line is not None:
                return self._object_line_endpoints(line)
        return None

    def _circle(self, name: str) -> _PathGeometry | None:
        inline = re.fullmatch(
            r"(Incircle|Circle)\[(.+?),\s*(.+?),\s*(.+?)\]",
            name,
            re.IGNORECASE,
        )
        if inline:
            refs = [self._point(inline.group(index)) for index in range(2, 5)]
            if all(refs):
                dependencies = refs[0][1] | refs[1][1] | refs[2][1]
                helper = "incircle" if inline.group(1).lower() == "incircle" else "circumcircle"
                return _PathGeometry(
                    f"{helper}({refs[0][0]},{refs[1][0]},{refs[2][0]})",
                    dependencies,
                )
        obj = self.objects_by_name.get(name)
        if obj is None or obj.kind != "conic":
            return None
        command = str(obj.attrs.get("command", "")).lower()
        inputs = list(obj.attrs.get("inputs", []))
        if command == "circle" and len(inputs) >= 3:
            refs = [self._point(item) for item in inputs[:3]]
            if all(refs):
                dependencies = refs[0][1] | refs[1][1] | refs[2][1]
                return _PathGeometry(
                    f"circumcircle({refs[0][0]},{refs[1][0]},{refs[2][0]})",
                    dependencies,
                )
        if command == "circle" and len(inputs) == 2:
            center = self._point(inputs[0])
            second = self._point(inputs[1])
            if center and second:
                return _PathGeometry(
                    f"circle({center[0]},abs({second[0]}-{center[0]}))",
                    center[1] | second[1],
                )
            radius = self._numeric(inputs[1])
            if center and radius is not None:
                return _PathGeometry(f"circle({center[0]},{radius})", center[1])
        if command == "incircle" and len(inputs) >= 3:
            refs = [self._point(item) for item in inputs[:3]]
            if all(refs):
                dependencies = refs[0][1] | refs[1][1] | refs[2][1]
                return _PathGeometry(
                    f"incircle({refs[0][0]},{refs[1][0]},{refs[2][0]})",
                    dependencies,
                )
        return None

    def _path(self, name: str) -> _PathGeometry | None:
        line = self._line(name)
        if line:
            return _PathGeometry(line.path, line.dependencies)
        return self._circle(name)

    def _resolve_command(self, obj: GgbObject) -> SymbolicPoint | None:
        command = str(obj.attrs.get("command", "")).lower()
        inputs = list(obj.attrs.get("inputs", []))

        if command == "midpoint":
            endpoints = self._line_endpoints(inputs)
            if endpoints:
                first, second, dependencies = endpoints
                return SymbolicPoint(f"({first}+{second})/2", dependencies)

        if command == "intersect" and len(inputs) >= 2:
            first_line = self._line(inputs[0])
            second_line = self._line(inputs[1])
            if (
                first_line
                and second_line
                and self._validated_line_intersection(
                    inputs[0], inputs[1], self.points[obj.name]
                )
            ):
                return SymbolicPoint(
                    f"extension({first_line.point},{first_line.point}+({first_line.direction}),"
                    f"{second_line.point},{second_line.point}+({second_line.direction}))",
                    first_line.dependencies | second_line.dependencies,
                )
            first_path = self._path(inputs[0])
            second_path = self._path(inputs[1])
            if first_path and second_path:
                return SymbolicPoint(
                    f"closestIntersection({first_path.code},{second_path.code},"
                    f"{self.pair_literal(self.points[obj.name])})",
                    first_path.dependencies | second_path.dependencies,
                    needs_intersection_helper=True,
                )

        if command in {"center", "centre"} and inputs:
            inline = re.fullmatch(
                r"(Incircle|Circle)\[(.+?),\s*(.+?),\s*(.+?)\]",
                inputs[0],
                re.IGNORECASE,
            )
            if inline:
                refs = [self._point(inline.group(index)) for index in range(2, 5)]
                if all(refs):
                    dependencies = refs[0][1] | refs[1][1] | refs[2][1]
                    helper = "incenter" if inline.group(1).lower() == "incircle" else "circumcenter"
                    return SymbolicPoint(
                        f"{helper}({refs[0][0]},{refs[1][0]},{refs[2][0]})",
                        dependencies,
                    )
            circle = self.objects_by_name.get(inputs[0])
            if circle is not None:
                circle_inputs = list(circle.attrs.get("inputs", []))
                if str(circle.attrs.get("command", "")).lower() == "circle":
                    if len(circle_inputs) == 2:
                        center = self._point(circle_inputs[0])
                        if center:
                            return SymbolicPoint(center[0], center[1])
                    if len(circle_inputs) >= 3:
                        refs = [self._point(item) for item in circle_inputs[:3]]
                        if all(refs):
                            dependencies = refs[0][1] | refs[1][1] | refs[2][1]
                            return SymbolicPoint(
                                f"circumcenter({refs[0][0]},{refs[1][0]},{refs[2][0]})",
                                dependencies,
                            )

        center_commands = {
            "circumcenter": "circumcenter",
            "incenter": "incenter",
            "orthocenter": "orthocenter",
        }
        if command in center_commands and len(inputs) >= 3:
            refs = [self._point(item) for item in inputs[:3]]
            if all(refs):
                dependencies = refs[0][1] | refs[1][1] | refs[2][1]
                return SymbolicPoint(
                    f"{center_commands[command]}({refs[0][0]},{refs[1][0]},{refs[2][0]})",
                    dependencies,
                )

        if command == "centroid" and len(inputs) >= 3:
            refs = [self._point(item) for item in inputs[:3]]
            if all(refs):
                dependencies = refs[0][1] | refs[1][1] | refs[2][1]
                return SymbolicPoint(
                    f"({refs[0][0]}+{refs[1][0]}+{refs[2][0]})/3",
                    dependencies,
                )

        if command == "trianglecenter" and len(inputs) >= 4:
            refs = [self._point(item) for item in inputs[:3]]
            index = self._numeric(inputs[3])
            center_by_index = {
                "1": "incenter",
                "2": None,
                "3": "circumcenter",
                "4": "orthocenter",
            }
            normalized_index = None if index is None else f"{float(index):.12g}"
            if all(refs) and normalized_index in center_by_index:
                dependencies = refs[0][1] | refs[1][1] | refs[2][1]
                helper = center_by_index[normalized_index]
                code = (
                    f"({refs[0][0]}+{refs[1][0]}+{refs[2][0]})/3"
                    if helper is None
                    else f"{helper}({refs[0][0]},{refs[1][0]},{refs[2][0]})"
                )
                return SymbolicPoint(code, dependencies)

        if command == "foot" and len(inputs) >= 2:
            point = self._point(inputs[0])
            if len(inputs) >= 3:
                first = self._point(inputs[1])
                second = self._point(inputs[2])
                if point and first and second:
                    return SymbolicPoint(
                        f"foot({point[0]},{first[0]},{second[0]})",
                        point[1] | first[1] | second[1],
                    )
            line = self._line(inputs[1])
            if point and line:
                return SymbolicPoint(
                    f"foot({point[0]},{line.point},{line.point}+({line.direction}))",
                    point[1] | line.dependencies,
                )

        if command in {"mirror", "reflect"} and len(inputs) >= 2:
            point = self._point(inputs[0])
            center = self._point(inputs[1])
            if point and center:
                return SymbolicPoint(
                    f"2*{center[0]}-{point[0]}",
                    point[1] | center[1],
                )
            line = self._line(inputs[1])
            if point and line:
                return SymbolicPoint(
                    f"2*foot({point[0]},{line.point},{line.point}+({line.direction}))-{point[0]}",
                    point[1] | line.dependencies,
                )

        if command == "translate" and len(inputs) >= 2:
            point = self._point(inputs[0])
            vector = self.objects_by_name.get(inputs[1])
            if point and vector is not None:
                endpoints = self._object_line_endpoints(vector)
                if endpoints:
                    first, second, dependencies = endpoints
                    return SymbolicPoint(
                        f"{point[0]}+{second}-{first}",
                        point[1] | dependencies,
                    )

        if command in {"rotate", "dilate"} and len(inputs) >= 3:
            point = self._point(inputs[0])
            amount = self._numeric(inputs[1])
            center = self._point(inputs[2])
            if point and amount is not None and center:
                operation = "rotate" if command == "rotate" else "scale"
                if command == "rotate":
                    amount = f"180/pi*({amount})"
                return SymbolicPoint(
                    f"{operation}({amount},{center[0]})*{point[0]}",
                    point[1] | center[1],
                )
        return None


INTERSECTION_HELPER = """pair closestIntersection(path first, path second, pair expected) {
  pair[] candidates = intersectionpoints(first, second);
  if (candidates.length == 0) return expected;
  pair best = candidates[0];
  for (int index = 1; index < candidates.length; ++index)
    if (abs(candidates[index]-expected) < abs(best-expected)) best = candidates[index];
  return best;
}"""
