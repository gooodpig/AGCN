from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from grapher.interactive import generate_interactive_html


class InteractiveOutputTests(unittest.TestCase):
    def test_generates_offline_svg_preview_with_draggable_free_points(self):
        xml = """<geogebra><euclidianView><size width="800" height="600"/>
          <coordSystem xZero="400" yZero="300" scale="50" yscale="50"/>
          <evSettings axes="true" grid="false"/></euclidianView><construction>
          <element type="point" label="A"><show object="true" label="true"/><coords x="0" y="0" z="1"/></element>
          <element type="point" label="B"><show object="true" label="true"/><coords x="4" y="0" z="1"/></element>
          <command name="Midpoint"><input a0="A" a1="B"/><output a0="M"/></command>
          <element type="point" label="M"><show object="true" label="true"/><coords x="2" y="0" z="1"/></element>
          <command name="Segment"><input a0="A" a1="M"/><output a0="s"/></command>
          <element type="segment" label="s"><show object="true" label="false"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as directory:
            source = Path(directory) / "sample.ggb"
            destination = Path(directory) / "sample.html"
            with ZipFile(source, "w") as archive:
                archive.writestr("geogebra.xml", xml)
            page = generate_interactive_html(source, destination)

            self.assertEqual(destination.read_text(encoding="utf-8"), page)
            self.assertIn('<svg id="stage"', page)
            self.assertIn("movableNames.push", page)
            self.assertIn("command==='midpoint'", page)
            self.assertIn("function constrainMovable", page)
            self.assertIn("command==='tangent'", page)
            self.assertIn("command==='point'", page)
            self.assertIn("function chooseLabelLayout", page)
            self.assertIn("function appendLabelContent", page)
            self.assertIn("'baseline-shift':'sub'", page)
            self.assertIn("r:radius", page)
            self.assertNotIn("registerUpdateListener", page)
            self.assertNotIn("geogebra.org", page)
            self.assertNotIn("ggbBase64", page)

    def test_escapes_script_terminators_in_object_names(self):
        xml = """<geogebra><construction><element type="point" label="&lt;/script&gt;">
          <show object="true" label="true"/><coords x="1" y="2" z="1"/>
        </element></construction></geogebra>"""
        with TemporaryDirectory() as directory:
            source = Path(directory) / "escape.ggb"
            with ZipFile(source, "w") as archive:
                archive.writestr("geogebra.xml", xml)
            page = generate_interactive_html(source)

        self.assertIn("\\u003c/script>", page)
        self.assertEqual(page.count("</script>"), 1)

    def test_inline_foot_circle_radius_is_available_to_dynamic_solver(self):
        xml = """<geogebra><construction>
          <element type="point" label="H"><show object="true" label="true"/><coords x="0" y="2" z="1"/></element>
          <element type="point" label="B_1"><show object="true" label="true"/><coords x="-2" y="0" z="1"/></element>
          <element type="point" label="C_1"><show object="true" label="true"/><coords x="2" y="0" z="1"/></element>
          <command name="Circle"><input a0="H" a1="Foot[H, B_1, C_1]"/><output a0="c"/></command>
          <element type="conic" label="c"><show object="true" label="false"/><matrix A0="1" A1="1" A2="0" A3="0" A4="0" A5="-2"/></element>
        </construction></geogebra>"""
        with TemporaryDirectory() as directory:
            source = Path(directory) / "inline-foot.ggb"
            with ZipFile(source, "w") as archive:
                archive.writestr("geogebra.xml", xml)
            page = generate_interactive_html(source)

        self.assertIn("Foot[H, B_1, C_1]", page)
        self.assertIn("/^Foot\\[", page)


if __name__ == "__main__":
    unittest.main()
