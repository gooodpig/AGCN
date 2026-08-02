from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
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
            self.assertIn("1.5*", code)

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
            self.assertIn('label("$E$", pE, N);', code)
            self.assertIn('label("$F$", F, N);', code)
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
            self.assertIn('label("$A\'$", Ap, 1.5*SW);', code)
    def test_output_file_and_debug_comments(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ggb_path = root / "sample.ggb"
            asy_path = root / "sample.asy"
            make_ggb(ggb_path)
            result = convert_ggb_to_asy(ggb_path, asy_path, debug=True)
            self.assertEqual(asy_path.read_text(encoding="utf-8"), result.code)
            self.assertIn("// parsed objects: 5", result.code)


if __name__ == "__main__":
    unittest.main()












