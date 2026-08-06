"""Camera-free tests for native GStreamer capture."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from camera_capture.backends import NativeGStreamerCapture, build_gstreamer_pipeline
from camera_capture.models import CaptureConfig
from capture_shared.errors import CaptureError


class Fraction:
    def __init__(self, numerator: int = 30, denominator: int = 1) -> None:
        self.numerator = numerator
        self.denominator = denominator


class Structure:
    def __init__(
        self,
        *,
        width: object = 2,
        height: object = 2,
        pixel_format: object = "BGR",
        framerate: object = None,
    ) -> None:
        self.values = {
            "width": width,
            "height": height,
            "format": pixel_format,
            "framerate": framerate if framerate is not None else Fraction(),
        }

    def get_value(self, name: str) -> object:
        return self.values[name]


class Buffer:
    def __init__(self, data: bytes, *, maps: bool = True) -> None:
        self.data = bytearray(data)
        self.maps = maps
        self.unmapped = False

    def map(self, _flags: object) -> tuple[bool, SimpleNamespace]:
        return self.maps, SimpleNamespace(data=self.data)

    def unmap(self, _mapped: object) -> None:
        self.unmapped = True


class Caps:
    def __init__(self, structure: Structure | None, *, size: int = 1) -> None:
        self.structure = structure
        self.size = size

    def get_size(self) -> int:
        return self.size

    def get_structure(self, _index: int) -> Structure | None:
        return self.structure


class Sample:
    def __init__(self, buffer: Buffer | None, caps: Caps | None) -> None:
        self.buffer = buffer
        self.caps = caps

    def get_buffer(self) -> Buffer | None:
        return self.buffer

    def get_caps(self) -> Caps | None:
        return self.caps


class AppSink:
    def __init__(self, samples: list[Sample | None]) -> None:
        self.samples = samples
        self.calls: list[tuple[object, object]] = []

    def emit(self, operation: object, timeout: object) -> Sample | None:
        self.calls.append((operation, timeout))
        return self.samples.pop(0) if self.samples else None


class FakeGst:
    MSECOND = 1

    class MapFlags:
        READ = "read"

    class State:
        NULL = "null"


def make_capture(
    samples: list[Sample | None],
    *,
    custom_pipeline: bool = True,
) -> NativeGStreamerCapture:
    capture = object.__new__(NativeGStreamerCapture)
    capture._Gst = FakeGst  # noqa: SLF001 - native boundary fixture
    capture._config = CaptureConfig(  # noqa: SLF001 - native boundary fixture
        output_dir=Path("."),
        frame_width=2,
        frame_height=2,
        fps=30,
        gstreamer_pipeline="test pipeline" if custom_pipeline else None,
    )
    capture._appsink = AppSink(samples)  # noqa: SLF001 - native boundary fixture
    capture._pipeline = MagicMock()  # noqa: SLF001 - native boundary fixture
    capture._opened = True  # noqa: SLF001 - native boundary fixture
    capture._caps_verified = False  # noqa: SLF001 - native boundary fixture
    capture._reporter = None  # noqa: SLF001 - native boundary fixture
    return capture


@contextmanager
def fake_gi(gst: object):
    gi = ModuleType("gi")
    setattr(gi, "require_version", MagicMock())
    repository = ModuleType("gi.repository")
    setattr(repository, "Gst", gst)
    setattr(gi, "repository", repository)
    with patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}):
        yield


class GStreamerPipelineTests(unittest.TestCase):
    def test_builds_exact_usb_v4l2_pipeline(self):
        config = CaptureConfig(
            output_dir=Path("."), camera_index=3, frame_width=640, frame_height=480, fps=25
        )

        self.assertEqual(
            "v4l2src device=/dev/video3 ! videoconvert ! "
            "video/x-raw,format=BGR,width=640,height=480,framerate=25/1 ! "
            "appsink name=appsink drop=true sync=false max-buffers=1",
            build_gstreamer_pipeline(config),
        )

    def test_builds_exact_jetson_pipeline_with_defaults(self):
        config = CaptureConfig(output_dir=Path("."), gstreamer_source="jetson-csi")

        self.assertEqual(
            "nvarguscamerasrc sensor-id=0 ! "
            "video/x-raw(memory:NVMM),width=(int)1280,height=(int)720,"
            "framerate=(fraction)30/1 ! nvvidconv ! "
            "video/x-raw,format=(string)BGRx ! videoconvert ! "
            "video/x-raw,format=(string)BGR ! "
            "appsink name=appsink drop=true sync=false max-buffers=1",
            build_gstreamer_pipeline(config),
        )

    def test_custom_pipeline_is_returned_unchanged(self):
        pipeline = "videotestsrc ! video/x-raw,format=BGR ! appsink name=appsink"
        config = CaptureConfig(output_dir=Path("."), gstreamer_pipeline=pipeline)

        self.assertEqual(pipeline, build_gstreamer_pipeline(config))


class NativeGStreamerReadTests(unittest.TestCase):
    def test_constructor_wraps_pipeline_parse_failure(self):
        gst = SimpleNamespace(
            init=MagicMock(),
            parse_launch=MagicMock(side_effect=ValueError("bad pipeline")),
        )

        with fake_gi(gst):
            with self.assertRaisesRegex(CaptureError, "Invalid GStreamer pipeline"):
                NativeGStreamerCapture(
                    CaptureConfig(output_dir=Path("."), gstreamer_pipeline="invalid")
                )

    def test_constructor_requires_named_appsink(self):
        pipeline = MagicMock()
        pipeline.get_by_name.return_value = None
        gst = SimpleNamespace(init=MagicMock(), parse_launch=MagicMock(return_value=pipeline))

        with fake_gi(gst):
            with self.assertRaisesRegex(CaptureError, "appsink named 'appsink'"):
                NativeGStreamerCapture(
                    CaptureConfig(output_dir=Path("."), gstreamer_pipeline="fakesrc ! fakesink")
                )

    def test_constructor_reports_failed_playing_state_as_not_opened(self):
        pipeline = MagicMock()
        pipeline.get_by_name.return_value = MagicMock()
        pipeline.set_state.return_value = "failure"
        gst = SimpleNamespace(
            init=MagicMock(),
            parse_launch=MagicMock(return_value=pipeline),
            State=SimpleNamespace(PLAYING="playing"),
            StateChangeReturn=SimpleNamespace(FAILURE="failure"),
        )

        with fake_gi(gst):
            capture = NativeGStreamerCapture(
                CaptureConfig(output_dir=Path("."), gstreamer_pipeline="test pipeline")
            )

        self.assertFalse(capture.isOpened())
        pipeline.set_state.assert_called_once_with("playing")

    def test_reporter_receives_pipeline_text(self):
        capture = make_capture([])
        capture._pipeline_text = "videotestsrc ! appsink name=appsink"  # noqa: SLF001
        lines = []

        capture.set_reporter(lines.append)

        self.assertEqual(["GStreamer pipeline: videotestsrc ! appsink name=appsink"], lines)

    def test_read_returns_no_frame_when_pipeline_is_not_open(self):
        capture = make_capture([])
        capture._opened = False  # noqa: SLF001 - native boundary fixture

        self.assertEqual((False, None), capture.read())
        self.assertEqual([], capture._appsink.calls)  # noqa: SLF001

    def test_read_converts_and_copies_bgr_buffer(self):
        buffer = Buffer(bytes(range(12)))
        capture = make_capture([Sample(buffer, Caps(Structure()))])

        ok, frame = capture.read()
        buffer.data[0] = 255

        self.assertTrue(ok)
        self.assertIsInstance(frame, np.ndarray)
        self.assertEqual((2, 2, 3), frame.shape)
        self.assertEqual(np.uint8, frame.dtype)
        self.assertEqual(0, frame[0, 0, 0])
        self.assertTrue(buffer.unmapped)

    def test_read_uses_bounded_appsink_timeout(self):
        capture = make_capture([None])

        self.assertEqual((False, None), capture.read())
        self.assertEqual([("try-pull-sample", 100)], capture._appsink.calls)  # noqa: SLF001

    def test_read_rejects_incomplete_sample_or_caps(self):
        cases = {
            "missing buffer": Sample(None, Caps(Structure())),
            "missing caps": Sample(Buffer(bytes(12)), None),
            "empty caps": Sample(Buffer(bytes(12)), Caps(Structure(), size=0)),
            "missing structure": Sample(Buffer(bytes(12)), Caps(None)),
            "invalid width": Sample(Buffer(bytes(12)), Caps(Structure(width="bad"))),
            "nonpositive height": Sample(Buffer(bytes(12)), Caps(Structure(height=0))),
        }

        for name, sample in cases.items():
            with self.subTest(name=name):
                self.assertEqual((False, None), make_capture([sample]).read())

    def test_read_rejects_map_failure(self):
        buffer = Buffer(bytes(12), maps=False)

        self.assertEqual((False, None), make_capture([Sample(buffer, Caps(Structure()))]).read())
        self.assertFalse(buffer.unmapped)

    def test_read_rejects_short_buffer_and_still_unmaps(self):
        buffer = Buffer(bytes(11))

        self.assertEqual((False, None), make_capture([Sample(buffer, Caps(Structure()))]).read())
        self.assertTrue(buffer.unmapped)

    def test_caps_are_verified_only_for_first_sample(self):
        samples = [
            Sample(Buffer(bytes(12)), Caps(Structure())),
            Sample(Buffer(bytes(12)), Caps(Structure())),
        ]
        capture = make_capture(samples)
        original = capture._verify_caps  # noqa: SLF001
        capture._verify_caps = MagicMock(wraps=original)  # noqa: SLF001

        self.assertTrue(capture.read()[0])
        self.assertTrue(capture.read()[0])

        capture._verify_caps.assert_called_once()  # noqa: SLF001

    def test_custom_pipeline_accepts_its_own_dimensions_and_fps(self):
        capture = make_capture([])

        capture._verify_caps(Structure(framerate=Fraction(15, 1)), 320, 240)  # noqa: SLF001

    def test_custom_pipeline_still_requires_bgr(self):
        capture = make_capture([])

        with self.assertRaisesRegex(CaptureError, "unsupported caps"):
            capture._verify_caps(Structure(pixel_format="RGB"), 2, 2)  # noqa: SLF001

    def test_generated_pipeline_rejects_each_caps_mismatch(self):
        cases = {
            "width": (Structure(), 3, 2),
            "height": (Structure(), 2, 3),
            "fps": (Structure(framerate=Fraction(15, 1)), 2, 2),
        }

        for name, (structure, width, height) in cases.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(CaptureError, "did not apply requested caps"):
                    make_capture([], custom_pipeline=False)._verify_caps(  # noqa: SLF001
                        structure, width, height
                    )

    def test_framerate_accepts_common_fraction_and_numeric_forms(self):
        capture = make_capture([])
        fraction = SimpleNamespace(num=30000, denom=1000)

        capture._verify_caps(Structure(framerate=fraction), 2, 2)  # noqa: SLF001
        capture._verify_caps(Structure(framerate=30.0), 2, 2)  # noqa: SLF001

    def test_framerate_uses_typed_gstreamer_fraction_reader(self):
        class GstStructure(Structure):
            def get_fraction(self, name):
                self.assert_field(name)
                return True, 30000, 1000

            def get_value(self, name):
                if name == "framerate":
                    raise TypeError("unknown type GstFraction")
                return super().get_value(name)

            def assert_field(self, name):
                if name != "framerate":
                    raise AssertionError(name)

        capture = make_capture([])

        capture._verify_caps(GstStructure(), 2, 2)  # noqa: SLF001

    def test_invalid_typed_gstreamer_fraction_is_a_capture_error(self):
        class GstStructure(Structure):
            def get_fraction(self, _name):
                return False, 0, 1

        with self.assertRaisesRegex(CaptureError, "valid framerate"):
            make_capture([])._verify_caps(GstStructure(), 2, 2)  # noqa: SLF001

    def test_invalid_framerate_is_a_capture_error(self):
        capture = make_capture([])

        for value in (object(), Fraction(30, 0)):
            with self.subTest(value=value):
                with self.assertRaisesRegex(CaptureError, "valid framerate"):
                    capture._verify_caps(Structure(framerate=value), 2, 2)  # noqa: SLF001

    def test_release_stops_pipeline(self):
        capture = make_capture([])

        capture.release()

        capture._pipeline.set_state.assert_called_once_with(FakeGst.State.NULL)  # noqa: SLF001
        self.assertFalse(capture.isOpened())


def gstreamer_is_available() -> bool:
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        Gst.init(None)
        return all(
            Gst.ElementFactory.find(name) is not None for name in ("videotestsrc", "appsink")
        )
    except Exception:
        return False


@pytest.mark.gstreamer
@unittest.skipUnless(gstreamer_is_available(), "PyGObject and GStreamer test plugins required")
class NativeGStreamerIntegrationTests(unittest.TestCase):
    def test_reads_frame_from_videotestsrc_without_camera(self):
        pipeline = (
            "videotestsrc num-buffers=1 ! "
            "video/x-raw,width=64,height=48,framerate=30/1 ! "
            "videoconvert ! video/x-raw,format=BGR ! "
            "appsink name=appsink drop=true sync=false max-buffers=1"
        )
        capture = NativeGStreamerCapture(
            CaptureConfig(
                output_dir=Path("."),
                capture_backend="gstreamer",
                gstreamer_pipeline=pipeline,
            )
        )

        try:
            ok = False
            frame = None
            for _ in range(10):
                ok, frame = capture.read()
                if ok:
                    break

            self.assertTrue(ok)
            self.assertEqual((48, 64, 3), frame.shape)
            self.assertEqual(np.uint8, frame.dtype)
        finally:
            capture.release()
