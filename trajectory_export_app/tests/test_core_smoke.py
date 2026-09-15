from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from trajectory_export_app.config import ExportConfig
from trajectory_export_app.core import export_model


class Point:
    def __init__(self, x, y, z=0.0):
        self.X = x
        self.Y = y
        self.Z = z


class Segment:
    def __init__(self, index, start, end):
        self.index = index
        self.ConstructionGeometry = False
        self._start = Point(*start)
        self._end = Point(*end)

    def GetStartPoint2(self):
        return self._start

    def GetEndPoint2(self):
        return self._end

    def GetLength(self):
        return ((self._end.X - self._start.X) ** 2 + (self._end.Y - self._start.Y) ** 2 + (self._end.Z - self._start.Z) ** 2) ** 0.5

    def GetCurve(self):
        return None

    def GetType(self):
        return 0


class Transform:
    ArrayData = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]


class Sketch:
    Is3D = False

    def __init__(self):
        self.ModelToSketchTransform = Transform()
        self._segments = [
            Segment(0, (0, 0, 0), (0.001, 0, 0)),
            Segment(1, (0.001, 0, 0), (0.001, 0.001, 0)),
        ]

    def GetSketchSegments(self):
        return self._segments


class Feature:
    Name = "Sketch1"

    def __init__(self):
        self._sketch = Sketch()

    def GetTypeName2(self):
        return "ProfileFeature"

    def GetSpecificFeature2(self):
        return self._sketch

    def GetNextFeature(self):
        return None


class Model:
    FirstFeature = Feature()

    def GetPathName(self):
        return "C:/test/demo.SLDPRT"

    def GetTitle(self):
        return "demo.SLDPRT"

    def GetPartBox(self, include_hidden):
        del include_hidden
        return (-1, -1, -1, 2, 2, 1)


class CoreSmokeTest(unittest.TestCase):
    def test_export_model_reports_progress_and_writes_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "trajectory.csv"
            events = []
            result = export_model(
                Model(),
                ExportConfig(
                    sketch_name="Sketch1",
                    output_csv=output,
                    surface_offset_mm=None,
                ),
                progress=events.append,
            )
            self.assertTrue(output.exists())
            self.assertTrue(result.metadata_path.exists())
            self.assertEqual(result.point_count, 3)
            self.assertAlmostEqual(result.trajectory_length_mm, 2.0)
            self.assertEqual(events[-1].percent, 100.0)
            self.assertEqual(events[-1].stage, "complete")
            progress_values = [event.percent for event in events if event.percent is not None]
            self.assertEqual(progress_values, sorted(progress_values))


if __name__ == "__main__":
    unittest.main()
