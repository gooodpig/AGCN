from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
import math
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from grapher.converter import (
    _largest_free_sector_direction,
    _make_support,
    convert_ggb_to_asy,
)
from grapher.parser import parse_ggb


SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<geogebra format="5.0">
  <euclidianView>
    <size width="800" height="600"/>
    <coordSystem xZero="400" yZero="300" scale="40" yscale="40"/>
    <evSettings axes="false" grid="false"/>
  </euclidianView>
  <construction>
    <element type="point" label="A">
      <show object="true" label="true"/>
      <objColor r="21" g="101" b="192" alpha="0"/>
      <pointSize val="5"/>
      <coords x="2" y="4" z="2"/>
    </element>
    <element type="point" label="B">
      <show object="true" label="true"/>
      <coords x="8" y="6" z="2"/>
    </element>
    <command name="Segment">
      <input a0="A" a1="B"/>
      <output a0="s"/>
    </command>
    <element type="segment" label="s">
      <show object="true" label="false"/>
      <lineStyle thickness="5" type="0"/>
      <coords x="-1" y="3" z="-5"/>
    </element>
    <command name="Line">
      <input a0="A" a1="B"/>
      <output a0="hiddenLine"/>
    </command>
    <element type="line" label="hiddenLine">
      <show object="false" label="false"/>
      <coords x="-1" y="3" z="-5"/>
    </element>
    <command name="Circle">
      <input a0="A" a1="B"/>
      <output a0="c"/>
    </command>
    <element type="conic" label="c">
      <show object="true" label="false"/>
      <matrix A0="1" A1="1" A2="-4" A3="0" A4="0" A5="0"/>
    </element>
  </construction>
</geogebra>
"""


def make_ggb(path: Path, xml: str = SAMPLE_XML) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr("geogebra.xml", xml)


class ConverterTests(unittest.TestCase):
    def test_parser_merges_commands_with_elements(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.ggb"
            make_ggb(path)
            parsed = parse_ggb(path)
            self.assertEqual(len(parsed.objects), 5)
            segment = next(obj for obj in parsed.objects if obj.name == "s")
            self.assertEqual(segment.attrs["command"], "Segment")
            self.assertEqual(segment.attrs["inputs"], ["A", "B"])
            self.assertEqual(parsed.viewport.x_min, -10)
            self.assertEqual(parsed.viewport.y_max, 7.5)

    def test_converter_uses_homogeneous_point_coordinates(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.ggb"
            make_ggb(path)
            code = convert_ggb_to_asy(path).code
            self.assertIn("pair A = (1, 2);", code)
            self.assertIn("pair B = (4, 3);", code)
            self.assertIn("dot(A,", code)

    def test_indexed_point_label_uses_tex_subscript(self):
        xml = SAMPLE_XML.replace('label="A"', 'label="A_1"')
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "indexed-label.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path).code
            self.assertIn('label("$A_1$", A_1,', code)
            self.assertNotIn(r'$A\_1$', code)

    def test_segment_is_not_treated_as_infinite_line(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.ggb"
            make_ggb(path)
            code = convert_ggb_to_asy(path, preserve_style=False).code
            self.assertEqual(code.count("draw(A--B, thinline);"), 1)
            self.assertNotIn("hiddenLine", code)

    def test_circle_uses_geogebra_matrix(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.ggb"
            make_ggb(path)
            code = convert_ggb_to_asy(path, preserve_style=False).code
            self.assertIn("draw(circle(A, abs(B-A)), thinline);", code)

    def test_non_circular_conic_uses_implicit_contour(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.ggb"
            make_ggb(path, SAMPLE_XML.replace(
                'A0="1" A1="1" A2="-4"',
                'A0="1" A1="4" A2="-4"',
            ))
            code = convert_ggb_to_asy(path, preserve_style=False).code
            self.assertIn("real conicc(real x, real y)", code)
            self.assertIn("draw(contour(conicc, (-10, -7.5), (10, 7.5), new real[] {0}, 120), thinline);", code)

    def test_parser_reads_implicit_polynomial_coefficients(self):
        xml = """<geogebra><construction>
          <element type="implicitpoly" label="cubic">
            <show object="true" label="false"/>
            <coefficients rep="array" data="[[0,0,1,0],[0],[0],[-1]]"/>
          </element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cubic.ggb"
            make_ggb(path, xml)
            parsed = parse_ggb(path)
            self.assertEqual(
                parsed.objects[0].attrs["coefficients"],
                [[0.0, 0.0, 1.0, 0.0], [0.0], [0.0], [-1.0]],
            )

    def test_implicit_cubic_uses_normalized_contour(self):
        xml = """<geogebra><construction>
          <element type="implicitpoly" label="cubic">
            <show object="true" label="false"/>
            <coefficients rep="array" data="[[0,0,2,0],[0],[0],[-2]]"/>
          </element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cubic.ggb"
            make_ggb(path, xml)
            result = convert_ggb_to_asy(path, preserve_style=False)
            self.assertEqual(result.warnings, [])
            self.assertIn("import contour;", result.code)
            self.assertIn(
                "real curvecubic(real x, real y) { return -x^3+y^2; }",
                result.code,
            )
            self.assertIn(
                "draw(contour(curvecubic, (-10, -10), (10, 10), "
                "new real[] {0}, 180), thinline);",
                result.code,
            )

    def test_semicircle_uses_geogebra_side(self):
        xml = """<geogebra><construction>
          <element type="point" label="B"><show object="true" label="false"/><coords x="-2" y="0" z="1"/></element>
          <element type="point" label="C"><show object="true" label="false"/><coords x="2" y="0" z="1"/></element>
          <command name="Semicircle"><input a0="B" a1="C"/><output a0="c"/></command>
          <element type="conicpart" label="c"><show object="true" label="false"/><matrix A0="1" A1="1" A2="-4" A3="0" A4="0" A5="0"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "semicircle.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path).code
            self.assertIn("t*-3.1415927", code)

    def test_angle_between_segment_and_axis_is_drawn(self):
        xml = """<geogebra><construction>
          <element type="point" label="D"><show object="true" label="false"/><coords x="-1" y="1" z="1"/></element>
          <element type="point" label="E"><show object="true" label="false"/><coords x="1" y="-1" z="1"/></element>
          <command name="Segment"><input a0="D" a1="E"/><output a0="f"/></command>
          <element type="segment" label="f"><show object="true" label="false"/></element>
          <command name="Angle"><input a0="f" a1="xAxis"/><output a0="beta"/></command>
          <element type="angle" label="beta"><show object="true" label="false"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "line-angle.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path).code
            self.assertRegex(code, r"draw\(arc\(\(0, 0\), [0-9.]+, -45, 0\), thinline\);")

    def test_curve_line_intersections_do_not_get_dots(self):
        xml = """<geogebra><construction>
          <element type="point" label="A"><show object="true" label="true"/><objColor r="21" g="101" b="192"/><coords x="1" y="0" z="1"/></element>
          <element type="point" label="B"><show object="true" label="true"/><coords x="-1" y="0" z="1"/></element>
          <command name="Segment"><input a0="A" a1="B"/><output a0="s"/></command>
          <element type="segment" label="s"><show object="true" label="false"/></element>
          <element type="conic" label="c"><show object="true" label="false"/><matrix A0="1" A1="1" A2="-1" A3="0" A4="0" A5="0"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "curve-intersections.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path).code
            self.assertNotIn("dot(A,", code)
            self.assertNotIn("dot(B,", code)

    def test_default_blue_point_is_black_in_automatic_style(self):
        xml = """<geogebra><construction>
          <element type="point" label="A"><show object="true" label="true"/><objColor r="21" g="101" b="192"/><coords x="0" y="0" z="1"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "blue-point.ggb"
            make_ggb(path, xml)
            automatic = convert_ggb_to_asy(path).code
            exact = convert_ggb_to_asy(path, preserve_style=True).code
            self.assertIn("dot(A, dotpen);", automatic)
            self.assertNotIn("rgb(0.082352941,0.39607843,0.75294118)", automatic)
            self.assertIn("rgb(0.082352941,0.39607843,0.75294118)", exact)

    def test_visible_axes_preserve_geogebra_viewport_aspect(self):
        xml = """<geogebra>
          <euclidianView><size width="1600" height="900"/><coordSystem xZero="800" yZero="450" scale="100" yscale="100"/><evSettings axes="true" grid="false"/></euclidianView>
          <construction><element type="point" label="A"><show object="true" label="false"/><coords x="0" y="0" z="1"/></element></construction>
        </geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "axes.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path).code
            self.assertIn("draw(box((-8.8, -4.95), (8.8, 4.95)), invisible);", code)
            self.assertIn("draw((-8, 0)--(8, 0), axispen, Arrow(3));", code)
            self.assertIn("draw((0, -4.5)--(0, 4.5), axispen, Arrow(3));", code)
            self.assertIn('label("$x$", (8, 0), 1.5*NW);', code)
            self.assertIn('label("$y$", (0, 4.5), 1.5*SE);', code)

    def test_example_style_header_and_reserved_point_names(self):
        xml = """<geogebra><construction>
          <element type="point" label="E"><show object="true" label="true"/><coords x="1" y="2" z="1"/></element>
          <element type="point" label="D&apos;"><show object="true" label="true"/><coords x="3" y="4" z="1"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "names.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path).code
            self.assertTrue(code.startswith('usepackage("amsmath");\nsize(8cm, keepAspect=true);'))
            self.assertIn("pen thinline = linewidth(0.5);", code)
            self.assertIn("pair pE = (1, 2);", code)
            self.assertIn("pair Dp = (3, 4);", code)

    def test_geometric_intersection_does_not_get_dot(self):
        xml = """<geogebra><construction>
          <element type="point" label="A"><show object="true" label="true"/><coords x="0" y="0" z="1"/></element>
          <element type="point" label="B"><show object="true" label="true"/><coords x="2" y="0" z="1"/></element>
          <element type="point" label="C"><show object="true" label="true"/><coords x="1" y="0" z="1"/></element>
          <element type="point" label="D"><show object="true" label="true"/><coords x="1" y="-1" z="1"/></element>
          <element type="point" label="E"><show object="true" label="true"/><coords x="1" y="1" z="1"/></element>
          <command name="Segment"><input a0="A" a1="B"/><output a0="s1"/></command>
          <element type="segment" label="s1"><show object="true" label="false"/></element>
          <command name="Segment"><input a0="D" a1="E"/><output a0="s2"/></command>
          <element type="segment" label="s2"><show object="true" label="false"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "intersection.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path).code
            self.assertNotIn("dot(C, dotpen)", code)
            self.assertIn("dot(A, dotpen)", code)

    def test_anglemark_is_converted_to_acute_orientation(self):
        xml = """<geogebra><construction>
          <element type="point" label="A"><show object="true" label="true"/><coords x="1" y="0" z="1"/></element>
          <element type="point" label="V"><show object="true" label="true"/><coords x="0" y="0" z="1"/></element>
          <element type="point" label="C"><show object="true" label="true"/><coords x="-1" y="1" z="1"/></element>
          <command name="Angle"><input a0="A" a1="V" a2="C"/><output a0="alpha"/></command>
          <element type="angle" label="alpha"><show object="true" label="false"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "angle.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path).code
            self.assertRegex(code, r"draw\(arc\(V, [0-9.]+, 135, 180\), thinline\);")
            self.assertNotIn("markscalefactor", code)

    def test_canvas_uses_compact_geometry_bounds_and_dense_labels_are_offset(self):
        xml = """<geogebra>
          <euclidianView><size width="800" height="600"/><coordSystem xZero="400" yZero="300" scale="40" yscale="40"/></euclidianView>
          <construction>
            <element type="point" label="A"><show object="true" label="true"/><coords x="0" y="0" z="1"/></element>
            <element type="point" label="B"><show object="true" label="true"/><coords x="0.1" y="0" z="1"/></element>
            <element type="point" label="C"><show object="true" label="true"/><coords x="10" y="10" z="1"/></element>
          </construction>
        </geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "layout.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path).code
            self.assertIn("draw(box((-0.8, -0.8), (10.8, 10.8)), invisible);", code)
            self.assertIn("clip(box((-0.8, -0.8), (10.8, 10.8)));", code)
            self.assertIn('label("$A$", A, SW);', code)
            self.assertIn('label("$B$", B, SE);', code)

    def test_largest_free_sector_prefers_northwest(self):
        point = (0.0, 0.0)
        endpoints = [(1.0, 1.7), (1.0, -0.5), (1.0, -1.3), (-1.0, -0.4)]
        supports = [_make_support(point, endpoint, "segment") for endpoint in endpoints]
        direction = _largest_free_sector_direction(point, supports, 1e-6)
        self.assertIsNotNone(direction)
        self.assertLess(direction[0], 0)
        self.assertGreater(direction[1], 0)

    def test_point_on_circle_label_moves_radially_outward(self):
        xml = """<geogebra><construction>
          <element type="point" label="O"><show object="true" label="false"/><coords x="0" y="0" z="1"/></element>
          <element type="point" label="Q"><show object="false" label="false"/><coords x="2" y="0" z="1"/></element>
          <element type="point" label="P"><show object="true" label="true"/><coords x="-2" y="0" z="1"/></element>
          <command name="Circle"><input a0="O" a1="Q"/><output a0="c"/></command>
          <element type="conic" label="c"><show object="true" label="false"/><matrix A0="1" A1="1" A2="-4" A3="0" A4="0" A5="0"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "circle-label.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path).code
            self.assertRegex(code, r'label\("\$P\$", P, (?:1\.\d+\*)?W\);')

    def test_circle_intersection_labels_avoid_radial_segments(self):
        xml = """<geogebra><construction>
          <element type="point" label="A"><show object="true" label="false"/><coords x="1.6308193" y="2.3125954" z="1"/></element>
          <element type="point" label="B"><show object="true" label="false"/><coords x="1.2137827" y="1.5888128" z="1"/></element>
          <element type="point" label="C"><show object="true" label="false"/><coords x="2.1081711" y="1.5888128" z="1"/></element>
          <element type="point" label="E"><show object="true" label="true"/><coords x="1.4657863" y="1.7927464" z="1"/></element>
          <element type="point" label="F"><show object="true" label="true"/><coords x="1.8197207" y="1.8222409" z="1"/></element>
          <command name="Segment"><input a0="E" a1="B"/><output a0="s1"/></command>
          <element type="segment" label="s1"><show object="true" label="false"/></element>
          <command name="Segment"><input a0="E" a1="C"/><output a0="s2"/></command>
          <element type="segment" label="s2"><show object="true" label="false"/></element>
          <command name="Segment"><input a0="F" a1="B"/><output a0="s3"/></command>
          <element type="segment" label="s3"><show object="true" label="false"/></element>
          <command name="Segment"><input a0="F" a1="C"/><output a0="s4"/></command>
          <element type="segment" label="s4"><show object="true" label="false"/></element>
          <command name="Circle"><input a0="A" a1="E" a2="F"/><output a0="circle1"/></command>
          <element type="conic" label="circle1"><show object="true" label="false"/><matrix A0="1" A1="1" A2="6.67267621935051" A3="0" A4="-1.6243334889281469" A5="-2.028533927255674"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "circle-intersections.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path).code
            self.assertRegex(code, r'label\("\$E\$", pE, (?:1\.\d+\*)?(?:N|NE)\);')
            self.assertRegex(code, r'label\("\$F\$", F, (?:1\.\d+\*)?(?:N|NW)\);')
    def test_global_layout_avoids_dense_label_box_overlaps(self):
        xml = """<geogebra><construction>
          <element type="point" label="A"><show object="true" label="true"/><coords x="0" y="0" z="1"/></element>
          <element type="point" label="B"><show object="true" label="true"/><coords x="0.08" y="0.02" z="1"/></element>
          <element type="point" label="C"><show object="true" label="true"/><coords x="-0.08" y="0.03" z="1"/></element>
          <element type="point" label="D"><show object="true" label="true"/><coords x="0.02" y="0.1" z="1"/></element>
          <element type="point" label="E"><show object="true" label="true"/><coords x="-0.02" y="-0.1" z="1"/></element>
          <element type="point" label="F"><show object="true" label="true"/><coords x="0.1" y="-0.08" z="1"/></element>
          <element type="point" label="Z"><show object="true" label="false"/><coords x="4" y="4" z="1"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "dense-labels.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path).code

        canvas = re.search(
            r"draw\(box\(\(([-0-9.]+), ([-0-9.]+)\), "
            r"\(([-0-9.]+), ([-0-9.]+)\)\), invisible\);",
            code,
        )
        self.assertIsNotNone(canvas)
        scale = max(
            float(canvas.group(3)) - float(canvas.group(1)),
            float(canvas.group(4)) - float(canvas.group(2)),
        )
        point_matches = re.findall(
            r"pair (\w+) = \(([-0-9.]+), ([-0-9.]+)\);", code
        )
        point_coords = {
            name: (float(x_coord), float(y_coord))
            for name, x_coord, y_coord in point_matches
        }
        vectors = {
            "E": (1.0, 0.0), "NE": (math.sqrt(0.5), math.sqrt(0.5)),
            "N": (0.0, 1.0), "NW": (-math.sqrt(0.5), math.sqrt(0.5)),
            "W": (-1.0, 0.0), "SW": (-math.sqrt(0.5), -math.sqrt(0.5)),
            "S": (0.0, -1.0), "SE": (math.sqrt(0.5), -math.sqrt(0.5)),
        }
        boxes = []
        for name, variable, factor_text, direction in re.findall(
            r'label\("\$([A-F])\$", (\w+), (?:(\d+(?:\.\d+)?)\*)?'
            r'(NE|NW|SE|SW|N|S|E|W)\);',
            code,
        ):
            factor = float(factor_text or 1.0)
            vector = vectors[direction]
            width = 0.03 * scale
            height = 0.032 * scale
            projected_extent = (
                abs(vector[0]) * width / 2 + abs(vector[1]) * height / 2
            )
            distance = projected_extent + factor * 0.010 * scale
            center = (
                point_coords[variable][0] + distance * vector[0],
                point_coords[variable][1] + distance * vector[1],
            )
            boxes.append((
                name,
                center[0] - width / 2,
                center[1] - height / 2,
                center[0] + width / 2,
                center[1] + height / 2,
            ))

        self.assertEqual(len(boxes), 6)
        for index, first in enumerate(boxes):
            for second in boxes[index + 1:]:
                overlap_x = min(first[3], second[3]) - max(first[1], second[1])
                overlap_y = min(first[4], second[4]) - max(first[2], second[2])
                self.assertFalse(
                    overlap_x > 0 and overlap_y > 0,
                    f"labels {first[0]} and {second[0]} overlap",
                )

    def test_auto_style_keeps_patterns_and_real_colors_but_maps_gray_to_black(self):
        xml = """<geogebra><construction>
          <element type="point" label="A"><show object="true" label="false"/><coords x="0" y="0" z="1"/></element>
          <element type="point" label="B"><show object="true" label="false"/><coords x="1" y="0" z="1"/></element>
          <element type="point" label="C"><show object="true" label="false"/><coords x="2" y="0" z="1"/></element>
          <command name="Segment"><input a0="A" a1="B"/><output a0="grayDashed"/></command>
          <element type="segment" label="grayDashed"><show object="true" label="false"/><objColor r="110" g="109" b="115"/><lineStyle thickness="5" type="15"/></element>
          <command name="Segment"><input a0="B" a1="C"/><output a0="cyanSolid"/></command>
          <element type="segment" label="cyanSolid"><show object="true" label="false"/><objColor r="0" g="255" b="255"/><lineStyle thickness="5" type="0"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "styles.ggb"
            make_ggb(path, xml)
            automatic = convert_ggb_to_asy(path).code
            exact = convert_ggb_to_asy(path, preserve_style=True).code
            self.assertIn("draw(A--B, dashed+thinline);", automatic)
            self.assertIn("draw(B--C, rgb(0,1,1)+thinline);", automatic)
            self.assertNotIn("rgb(0.43137255,0.42745098,0.45098039)", automatic)
            self.assertIn(
                "dashed+rgb(0.43137255,0.42745098,0.45098039)+linewidth(0.8bp)",
                exact,
            )

    def test_manual_geogebra_label_offset_is_respected(self):
        xml = """<geogebra><construction>
          <element type="point" label="A&apos;"><show object="true" label="true"/><labelOffset x="-26" y="25"/><coords x="0" y="0" z="1"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "label-offset.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path).code
            self.assertIn('label("$A\'$", Ap, SW);', code)

    def test_manual_label_offset_yields_to_visible_geometry(self):
        xml = """<geogebra><construction>
          <element type="point" label="A"><show object="true" label="true"/><labelOffset x="0" y="24"/><coords x="0" y="1" z="1"/></element>
          <element type="point" label="B"><show object="true" label="false"/><coords x="0" y="0" z="1"/></element>
          <command name="Segment"><input a0="A" a1="B"/><output a0="s"/></command>
          <element type="segment" label="s"><show object="true" label="false"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "manual-conflict.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path).code
            self.assertNotIn('label("$A$", A, S);', code)
            self.assertIn('label("$A$", A, SW);', code)

    def test_derivative_function_uses_valid_asymptote_definition(self):
        xml = """<geogebra><construction>
          <expression label="f" exp="f: y = sin(x)"/>
          <element type="function" label="f"><show object="true" label="false"/></element>
          <expression label="f&apos;" exp="f&apos;(x) = f&apos;(x)"/>
          <element type="function" label="f&apos;"><show object="true" label="false"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "derivative.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path).code
            self.assertIn("real ff(real x) { return sin(x); }", code)
            self.assertIn("real ffp(real x) { real h=1e-5*(1+abs(x));", code)
            self.assertNotIn("return f'(x)", code)

    def test_output_file_and_debug_comments(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ggb_path = root / "sample.ggb"
            asy_path = root / "sample.asy"
            make_ggb(ggb_path)
            result = convert_ggb_to_asy(ggb_path, asy_path, debug=True)
            self.assertEqual(asy_path.read_text(encoding="utf-8"), result.code)
            self.assertIn("// parsed objects: 5", result.code)

    def test_symbolic_points_prefer_construction_commands(self):
        xml = """<geogebra><construction>
          <element type="point" label="A"><show object="false" label="false"/><coords x="0" y="0" z="1"/></element>
          <element type="point" label="B"><show object="false" label="false"/><coords x="4" y="0" z="1"/></element>
          <element type="point" label="C"><show object="false" label="false"/><coords x="0" y="4" z="1"/></element>
          <command name="Midpoint"><input a0="A" a1="B"/><output a0="M"/></command>
          <element type="point" label="M"><show object="true" label="true"/><coords x="2" y="0" z="1"/></element>
          <command name="Line"><input a0="A" a1="C"/><output a0="l1"/></command>
          <element type="line" label="l1"><show object="false" label="false"/></element>
          <command name="Line"><input a0="B" a1="C"/><output a0="l2"/></command>
          <element type="line" label="l2"><show object="false" label="false"/></element>
          <command name="Intersect"><input a0="l1" a1="l2"/><output a0="P"/></command>
          <element type="point" label="P"><show object="true" label="true"/><coords x="0" y="4" z="1"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "symbolic.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path).code
            self.assertIn("pair A = (0, 0);", code)
            self.assertIn("pair B = (4, 0);", code)
            self.assertIn("pair C = (0, 4);", code)
            self.assertIn("pair M = (A+B)/2;", code)
            self.assertIn("pair P = extension(A,A+(C-A),B,B+(C-B));", code)

    def test_symbolic_circle_intersection_uses_coordinate_only_for_selection(self):
        xml = """<geogebra><construction>
          <element type="point" label="O"><show object="false" label="false"/><coords x="0" y="0" z="1"/></element>
          <element type="point" label="A"><show object="false" label="false"/><coords x="2" y="0" z="1"/></element>
          <element type="point" label="B"><show object="false" label="false"/><coords x="-3" y="0" z="1"/></element>
          <element type="point" label="C"><show object="false" label="false"/><coords x="3" y="0" z="1"/></element>
          <command name="Circle"><input a0="O" a1="A"/><output a0="c"/></command>
          <element type="conic" label="c"><show object="true" label="false"/><matrix A0="1" A1="1" A2="-4" A3="0" A4="0" A5="0"/></element>
          <command name="Line"><input a0="B" a1="C"/><output a0="l"/></command>
          <element type="line" label="l"><show object="true" label="false"/></element>
          <command name="Intersect"><input a0="c" a1="l" a2="2"/><output a0="P"/></command>
          <element type="point" label="P"><show object="true" label="true"/><coords x="2" y="0" z="1"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "circle-intersection.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path).code
            self.assertIn("pair closestIntersection(path first, path second, pair expected)", code)
            self.assertIn(
                "pair P = closestIntersection(circle(pO,abs(A-pO)),",
                code,
            )
            self.assertIn(",(2, 0));", code)

    def test_coordinates_only_disables_symbolic_points(self):
        xml = """<geogebra><construction>
          <element type="point" label="A"><show object="true" label="false"/><coords x="0" y="0" z="1"/></element>
          <element type="point" label="B"><show object="true" label="false"/><coords x="4" y="0" z="1"/></element>
          <command name="Midpoint"><input a0="A" a1="B"/><output a0="M"/></command>
          <element type="point" label="M"><show object="true" label="true"/><coords x="2" y="0" z="1"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "coordinates.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path, symbolic=False).code
            self.assertIn("pair M = (2, 0);", code)
            self.assertNotIn("pair M = (A+B)/2;", code)

    def test_symbolic_triangle_centers_inline_circles_and_three_point_feet(self):
        xml = """<geogebra><construction>
          <element type="point" label="A"><show object="false" label="false"/><coords x="0" y="3" z="1"/></element>
          <element type="point" label="B"><show object="false" label="false"/><coords x="-2" y="0" z="1"/></element>
          <element type="point" label="C"><show object="false" label="false"/><coords x="2" y="0" z="1"/></element>
          <command name="TriangleCenter"><input a0="A" a1="B" a2="C" a3="1"/><output a0="I"/></command>
          <element type="point" label="I"><show object="true" label="true"/><coords x="0" y="1" z="1"/></element>
          <command name="Center"><input a0="Incircle[A, B, C]"/><output a0="J"/></command>
          <element type="point" label="J"><show object="true" label="true"/><coords x="0" y="1" z="1"/></element>
          <command name="Foot"><input a0="I" a1="B" a2="C"/><output a0="D"/></command>
          <element type="point" label="D"><show object="true" label="true"/><coords x="0" y="0" z="1"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "expanded-symbolic.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path).code

        self.assertIn("pair pI = incenter(A,B,C);", code)
        self.assertIn("pair J = incenter(A,B,C);", code)
        self.assertIn("pair D = foot(pI,B,C);", code)

    def test_symbolic_intersections_use_the_correct_polygon_edges(self):
        xml = """<geogebra><construction>
          <element type="point" label="B"><show object="false" label="false"/><coords x="0" y="0" z="1"/></element>
          <element type="point" label="C"><show object="false" label="false"/><coords x="4" y="0" z="1"/></element>
          <element type="point" label="H"><show object="false" label="false"/><coords x="0" y="4" z="1"/></element>
          <element type="point" label="E"><show object="false" label="false"/><coords x="-1" y="2" z="1"/></element>
          <element type="point" label="F"><show object="false" label="false"/><coords x="5" y="2" z="1"/></element>
          <command name="Polygon"><input a0="B" a1="C" a2="H"/><output a0="tri" a1="h" a2="b_1" a3="c_1"/></command>
          <element type="polygon" label="tri"><show object="false" label="false"/></element>
          <element type="segment" label="h"><show object="false" label="false"/></element>
          <element type="segment" label="b_1"><show object="false" label="false"/></element>
          <element type="segment" label="c_1"><show object="false" label="false"/></element>
          <command name="Intersect"><input a0="Line[E, F]" a1="b_1"/><output a0="B_1"/></command>
          <element type="point" label="B_1"><show object="true" label="true"/><coords x="2" y="2" z="1"/></element>
          <command name="Intersect"><input a0="Line[E, F]" a1="c_1"/><output a0="C_1"/></command>
          <element type="point" label="C_1"><show object="true" label="true"/><coords x="0" y="2" z="1"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "polygon-edges.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path).code

        self.assertIn("pair B_1 = extension(pE,pE+(F-pE),C,C+(H-C));", code)
        self.assertIn("pair C_1 = extension(pE,pE+(F-pE),H,H+(B-H));", code)

    def test_line_bisector_is_not_treated_as_line_through_endpoints(self):
        xml = """<geogebra><construction>
          <element type="point" label="A"><show object="false" label="false"/><coords x="0" y="0" z="1"/></element>
          <element type="point" label="B"><show object="false" label="false"/><coords x="4" y="0" z="1"/></element>
          <element type="point" label="C"><show object="false" label="false"/><coords x="0" y="0" z="1"/></element>
          <element type="point" label="D"><show object="false" label="false"/><coords x="0" y="2" z="1"/></element>
          <command name="LineBisector"><input a0="A" a1="B"/><output a0="m1"/></command>
          <element type="line" label="m1"><show object="false" label="false"/></element>
          <command name="LineBisector"><input a0="C" a1="D"/><output a0="m2"/></command>
          <element type="line" label="m2"><show object="false" label="false"/></element>
          <command name="Intersect"><input a0="m1" a1="m2"/><output a0="P"/></command>
          <element type="point" label="P"><show object="true" label="true"/><coords x="2" y="1" z="1"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bisectors.ggb"
            make_ggb(path, xml)
            code = convert_ggb_to_asy(path).code
            self.assertIn(
                "extension((A+B)/2,(A+B)/2+(rotate(90)*(B-A)),",
                code,
            )


if __name__ == "__main__":
    unittest.main()
