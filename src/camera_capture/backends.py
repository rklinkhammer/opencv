"""Backend adapters for OpenCV and native GStreamer frame ingestion."""

from __future__ import annotations

from contextlib import contextmanager
import math
from typing import Any, Callable, cast, Iterator, Literal, Protocol

import numpy as np

from capture_shared.errors import CaptureError, ConfigurationError

from .models import CaptureConfig
from .validators import camera_open_error, normalize_backend, normalize_fourcc

_GSTREAMER_SAMPLE_TIMEOUT_MILLISECONDS = 100
_FPS_REL_TOLERANCE = 0.05

Reporter = Callable[[str], None]
PropertyKind = Literal["fps", "integer", "boolean", "number"]


CAMERA_PROPERTIES: dict[str, tuple[str, PropertyKind]] = {
    "fps": ("CAP_PROP_FPS", "fps"),
    "frame_width": ("CAP_PROP_FRAME_WIDTH", "integer"),
    "frame_height": ("CAP_PROP_FRAME_HEIGHT", "integer"),
    "auto_exposure": ("CAP_PROP_AUTO_EXPOSURE", "number"),
    "exposure": ("CAP_PROP_EXPOSURE", "number"),
    "gain": ("CAP_PROP_GAIN", "number"),
    "brightness": ("CAP_PROP_BRIGHTNESS", "number"),
    "contrast": ("CAP_PROP_CONTRAST", "number"),
    "saturation": ("CAP_PROP_SATURATION", "number"),
    "hue": ("CAP_PROP_HUE", "number"),
    "gamma": ("CAP_PROP_GAMMA", "number"),
    "sharpness": ("CAP_PROP_SHARPNESS", "number"),
    "backlight": ("CAP_PROP_BACKLIGHT", "number"),
    "auto_white_balance": ("CAP_PROP_AUTO_WB", "boolean"),
    "white_balance_temperature": ("CAP_PROP_WB_TEMPERATURE", "number"),
    "white_balance_blue": ("CAP_PROP_WHITE_BALANCE_BLUE_U", "number"),
    "white_balance_red": ("CAP_PROP_WHITE_BALANCE_RED_V", "number"),
    "autofocus": ("CAP_PROP_AUTOFOCUS", "boolean"),
    "focus": ("CAP_PROP_FOCUS", "number"),
    "zoom": ("CAP_PROP_ZOOM", "number"),
    "pan": ("CAP_PROP_PAN", "number"),
    "tilt": ("CAP_PROP_TILT", "number"),
    "roll": ("CAP_PROP_ROLL", "number"),
    "buffer_size": ("CAP_PROP_BUFFERSIZE", "integer"),
}


class CaptureHandle(Protocol):
    """Small capture surface shared by OpenCV and native GStreamer."""

    def isOpened(self) -> bool: ...

    def read(self) -> tuple[bool, Any]: ...

    def release(self) -> None: ...


class CaptureBackend(Protocol):
    """Open and configure a capture handle without leaking backend branches upstream."""

    def open(self, config: CaptureConfig, cv2_module: Any) -> CaptureHandle: ...

    def configure(
        self,
        capture: CaptureHandle,
        config: CaptureConfig,
        cv2_module: Any,
        reporter: Reporter | None = None,
    ) -> None: ...


def apply_camera_settings(
    capture: Any,
    config: CaptureConfig,
    cv2_module: Any,
    reporter: Reporter | None = None,
) -> None:
    """Apply requested OpenCV properties and verify the values read back."""
    if reporter is not None:
        defaults = []
        for config_name, (opencv_name, _) in CAMERA_PROPERTIES.items():
            if hasattr(cv2_module, opencv_name):
                default = _try_read_camera_property(capture, opencv_name, cv2_module)
                value = "unavailable" if default is None else f"{default:g}"
                defaults.append(f"{_property_label(config_name)}={value}")
        if hasattr(cv2_module, "CAP_PROP_FOURCC"):
            fourcc_value = _try_read_camera_property(capture, "CAP_PROP_FOURCC", cv2_module)
            defaults.append(
                "fourcc=unavailable"
                if fourcc_value is None
                else f"fourcc={_format_fourcc(fourcc_value)}"
            )
        defaults.extend(_read_diagnostics(capture, cv2_module))
        reporter("Camera defaults: " + ", ".join(defaults))

    for config_name, (opencv_name, kind) in CAMERA_PROPERTIES.items():
        value = getattr(config, config_name)
        if value is not None:
            _set_and_verify(
                capture,
                cv2_module,
                _property_label(config_name),
                opencv_name,
                float(value),
                kind,
                reporter,
            )

    if config.fourcc:
        if not hasattr(cv2_module, "VideoWriter_fourcc"):
            raise CaptureError("OpenCV does not support setting fourcc")
        fourcc = normalize_fourcc(config.fourcc)
        assert fourcc is not None
        requested = float(cv2_module.VideoWriter_fourcc(*fourcc))
        _set_and_verify(
            capture,
            cv2_module,
            "fourcc",
            "CAP_PROP_FOURCC",
            requested,
            "integer",
            reporter,
            requested_display=fourcc,
        )


def _read_camera_property(capture: Any, constant: str, cv2_module: Any) -> float:
    try:
        value = float(capture.get(getattr(cv2_module, constant)))
    except Exception as exc:
        raise CaptureError(
            f"Unable to read camera setting {constant.removeprefix('CAP_PROP_').lower()}"
        ) from exc
    if not math.isfinite(value):
        raise CaptureError(f"Camera returned an invalid value for {constant}")
    return value


def _try_read_camera_property(capture: Any, constant: str, cv2_module: Any) -> float | None:
    try:
        return _read_camera_property(capture, constant, cv2_module)
    except CaptureError:
        return None


def _read_diagnostics(capture: Any, cv2_module: Any) -> list[str]:
    diagnostics = []
    if hasattr(capture, "getBackendName"):
        try:
            diagnostics.append(f"backend={capture.getBackendName()}")
        except Exception:
            pass
    for label, constant in (
        ("format", "CAP_PROP_FORMAT"),
        ("codec_pixel_format", "CAP_PROP_CODEC_PIXEL_FORMAT"),
        ("temperature", "CAP_PROP_TEMPERATURE"),
    ):
        if not hasattr(cv2_module, constant):
            continue
        try:
            diagnostics.append(f"{label}={_read_camera_property(capture, constant, cv2_module):g}")
        except CaptureError:
            diagnostics.append(f"{label}=unavailable")
    return diagnostics


def _set_and_verify(
    capture: Any,
    cv2_module: Any,
    label: str,
    constant: str,
    requested: float,
    kind: PropertyKind,
    reporter: Reporter | None,
    *,
    requested_display: str | None = None,
) -> None:
    if not hasattr(cv2_module, constant):
        raise CaptureError(f"OpenCV does not support setting {label}")
    try:
        accepted = capture.set(getattr(cv2_module, constant), requested)
    except Exception as exc:
        raise CaptureError(f"Unable to set camera {label}") from exc
    if not accepted:
        raise CaptureError(f"Camera rejected {label}={requested_display or f'{requested:g}'}")

    actual = _read_camera_property(capture, constant, cv2_module)
    if label == "fourcc" or kind == "integer":
        applied = int(actual) == int(requested)
    elif kind == "fps":
        applied = math.isclose(actual, requested, rel_tol=_FPS_REL_TOLERANCE, abs_tol=0.5)
    elif kind == "boolean":
        applied = actual in {0.0, 1.0} and actual == requested
    else:
        applied = math.isclose(actual, requested, abs_tol=0.5)
    if not applied:
        raise CaptureError(
            f"Camera did not apply {label}: requested={requested_display or f'{requested:g}'} "
            f"actual={_format_fourcc(actual) if label == 'fourcc' else f'{actual:g}'}"
        )
    if reporter is not None:
        reporter(
            f"Camera setting verified: {label}="
            f"{requested_display or f'{requested:g}'} (actual={_format_fourcc(actual) if label == 'fourcc' else f'{actual:g}'})"
        )


def _format_fourcc(value: float) -> str:
    encoded = int(value)
    text = "".join(chr((encoded >> shift) & 0xFF) for shift in (0, 8, 16, 24))
    return text if text.isprintable() and text.strip("\x00") else str(encoded)


def _property_label(config_name: str) -> str:
    return config_name.removeprefix("frame_")


def build_gstreamer_pipeline(config: CaptureConfig) -> str:
    """Return a custom pipeline unchanged or build one of the supported presets."""
    if config.gstreamer_pipeline:
        return config.gstreamer_pipeline

    source = config.gstreamer_source.lower().strip()
    width = config.frame_width if config.frame_width is not None else 1280
    height = config.frame_height if config.frame_height is not None else 720
    fps = int(config.fps)

    if source == "usb-v4l2":
        caps = [
            "video/x-raw",
            "format=BGR",
            f"width={width}",
            f"height={height}",
            f"framerate={fps}/1",
        ]
        caps_str = ",".join(caps)
        return (
            f"v4l2src device=/dev/video{config.camera_index} ! "
            "videoconvert ! "
            f"{caps_str} ! "
            "appsink name=appsink drop=true sync=false max-buffers=1"
        )

    if source == "jetson-csi":
        return (
            f"nvarguscamerasrc sensor-id={config.camera_index} ! "
            "video/x-raw(memory:NVMM),"
            f"width=(int){width},height=(int){height},framerate=(fraction){fps}/1 ! "
            "nvvidconv ! video/x-raw,format=(string)BGRx ! "
            "videoconvert ! video/x-raw,format=(string)BGR ! "
            "appsink name=appsink drop=true sync=false max-buffers=1"
        )

    raise ConfigurationError("gstreamer_source must be one of: usb-v4l2, jetson-csi")


class NativeGStreamerCapture:
    """Adapt a GStreamer appsink pipeline to the OpenCV capture interface."""

    def __init__(self, config: CaptureConfig):
        try:
            import gi

            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
        except ImportError as exc:
            raise CaptureError(
                "Native GStreamer backend requires PyGObject. "
                "Install python3-gi and gir1.2-gstreamer-1.0."
            ) from exc

        self._Gst = Gst
        Gst.init(None)

        self._config = config
        self._pipeline_text = build_gstreamer_pipeline(config)
        self._reporter: Reporter | None = None
        self._caps_verified = False
        try:
            pipeline = Gst.parse_launch(self._pipeline_text)
        except Exception as exc:
            raise CaptureError(f"Invalid GStreamer pipeline: {exc}") from exc

        appsink = pipeline.get_by_name("appsink")
        if appsink is None:
            raise CaptureError(
                "GStreamer pipeline must contain an appsink named 'appsink' "
                "for native backend frame extraction."
            )

        self._pipeline = pipeline
        self._appsink = appsink
        self._opened = False

        state_result = self._pipeline.set_state(Gst.State.PLAYING)
        if state_result != Gst.StateChangeReturn.FAILURE:
            self._opened = True

    def set_reporter(self, reporter: Reporter | None) -> None:
        self._reporter = reporter
        if reporter is not None:
            reporter(f"GStreamer pipeline: {self._pipeline_text}")

    def isOpened(self) -> bool:
        return self._opened

    def read(self) -> tuple[bool, Any]:
        if not self._opened:
            return False, None

        sample = self._appsink.emit(
            "try-pull-sample",
            _GSTREAMER_SAMPLE_TIMEOUT_MILLISECONDS * self._Gst.MSECOND,
        )
        if sample is None:
            return False, None

        buffer = sample.get_buffer()
        caps = sample.get_caps()
        if buffer is None or caps is None or caps.get_size() == 0:
            return False, None

        structure = caps.get_structure(0)
        if structure is None:
            return False, None

        try:
            width = int(structure.get_value("width"))
            height = int(structure.get_value("height"))
        except (TypeError, ValueError):
            return False, None

        if width <= 0 or height <= 0:
            return False, None

        if not self._caps_verified:
            self._verify_caps(structure, width, height)
            self._caps_verified = True

        ok, mapped = buffer.map(self._Gst.MapFlags.READ)
        if not ok:
            return False, None

        try:
            expected_size = width * height * 3
            if len(mapped.data) < expected_size:
                return False, None
            frame = np.frombuffer(mapped.data, dtype=np.uint8, count=expected_size).reshape(
                (height, width, 3)
            )
            frame = frame.copy()
            return True, frame
        finally:
            buffer.unmap(mapped)

    def _verify_caps(self, structure: Any, width: int, height: int) -> None:
        pixel_format = str(structure.get_value("format") or "")
        fps = _gstreamer_structure_fps(structure)
        details = f"width={width}, height={height}, fps={fps:g}, format={pixel_format}"
        if self._reporter is not None:
            self._reporter(f"GStreamer negotiated: {details}")

        if pixel_format != "BGR":
            raise CaptureError(f"GStreamer negotiated unsupported caps: {details}")
        if self._config.gstreamer_pipeline:
            return

        expected_width = self._config.frame_width or 1280
        expected_height = self._config.frame_height or 720
        if (
            width != expected_width
            or height != expected_height
            or not math.isclose(
                fps,
                self._config.fps,
                rel_tol=_FPS_REL_TOLERANCE,
                abs_tol=0.5,
            )
        ):
            raise CaptureError(
                "GStreamer did not apply requested caps: "
                f"requested=width={expected_width}, height={expected_height}, "
                f"fps={self._config.fps:g}, format=BGR; actual={details}"
            )

    def release(self) -> None:
        self._pipeline.set_state(self._Gst.State.NULL)
        self._opened = False


class OpenCvBackend:
    def open(self, config: CaptureConfig, cv2_module: Any) -> CaptureHandle:
        return cv2_module.VideoCapture(config.camera_index)

    def configure(
        self,
        capture: CaptureHandle,
        config: CaptureConfig,
        cv2_module: Any,
        reporter: Reporter | None = None,
    ) -> None:
        apply_camera_settings(capture, config, cv2_module, reporter)


class NativeGStreamerBackend:
    def open(self, config: CaptureConfig, cv2_module: Any) -> CaptureHandle:
        del cv2_module
        return NativeGStreamerCapture(config)

    def configure(
        self,
        capture: CaptureHandle,
        config: CaptureConfig,
        cv2_module: Any,
        reporter: Reporter | None = None,
    ) -> None:
        del config, cv2_module
        cast(NativeGStreamerCapture, capture).set_reporter(reporter)


def create_capture_backend(name: str) -> CaptureBackend:
    """Resolve a validated public backend name to its implementation."""
    backend = normalize_backend(name)
    if backend == "opencv":
        return OpenCvBackend()
    return NativeGStreamerBackend()


@contextmanager
def open_camera(
    config: CaptureConfig,
    cv2_module: Any,
    backend: CaptureBackend,
    reporter: Reporter | None = None,
) -> Iterator[CaptureHandle]:
    """Open, configure, and always release a camera capture handle."""
    capture = backend.open(config, cv2_module)
    try:
        if not capture.isOpened():
            raise CaptureError(camera_open_error(config.camera_index))
        backend.configure(capture, config, cv2_module, reporter)
        yield capture
    finally:
        try:
            capture.release()
        except Exception:
            pass


def _gstreamer_fps(value: Any) -> float:
    for numerator_name, denominator_name in (("numerator", "denominator"), ("num", "denom")):
        if hasattr(value, numerator_name) and hasattr(value, denominator_name):
            denominator = float(getattr(value, denominator_name))
            if denominator:
                return float(getattr(value, numerator_name)) / denominator
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise CaptureError("GStreamer caps do not contain a valid framerate") from exc


def _gstreamer_structure_fps(structure: Any) -> float:
    get_fraction = getattr(structure, "get_fraction", None)
    if get_fraction is not None:
        try:
            valid, numerator, denominator = get_fraction("framerate")
            if valid and denominator:
                return float(numerator) / float(denominator)
        except (TypeError, ValueError):
            pass
        raise CaptureError("GStreamer caps do not contain a valid framerate")

    try:
        return _gstreamer_fps(structure.get_value("framerate"))
    except (KeyError, TypeError, ValueError) as exc:
        raise CaptureError("GStreamer caps do not contain a valid framerate") from exc
