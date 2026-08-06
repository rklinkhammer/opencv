"""Backend adapters for OpenCV and native GStreamer frame ingestion."""

from __future__ import annotations

from contextlib import contextmanager
import math
from typing import Any, Iterator, Protocol

import numpy as np

from capture_shared.errors import CaptureError, ConfigurationError

from .models import CaptureConfig
from .validators import camera_open_error, normalize_backend, normalize_fourcc

_GSTREAMER_SAMPLE_TIMEOUT_MILLISECONDS = 100
_SETTING_TOLERANCE = 0.05


class CaptureHandle(Protocol):
    def isOpened(self) -> bool: ...

    def read(self) -> tuple[bool, Any]: ...

    def release(self) -> None: ...


class CaptureBackend(Protocol):
    def open(self, config: CaptureConfig, cv2_module: Any) -> CaptureHandle: ...

    def configure(
        self,
        capture: CaptureHandle,
        config: CaptureConfig,
        cv2_module: Any,
    ) -> None: ...


def apply_camera_settings(
    capture: Any,
    config: CaptureConfig,
    cv2_module: Any,
) -> None:
    settings: list[tuple[str, str, float | int | bool | None]] = [
        ("fps", "CAP_PROP_FPS", config.fps),
        ("width", "CAP_PROP_FRAME_WIDTH", config.frame_width),
        ("height", "CAP_PROP_FRAME_HEIGHT", config.frame_height),
        ("auto_exposure", "CAP_PROP_AUTO_EXPOSURE", config.auto_exposure),
        ("exposure", "CAP_PROP_EXPOSURE", config.exposure),
        ("gain", "CAP_PROP_GAIN", config.gain),
        ("brightness", "CAP_PROP_BRIGHTNESS", config.brightness),
        ("contrast", "CAP_PROP_CONTRAST", config.contrast),
        ("saturation", "CAP_PROP_SATURATION", config.saturation),
        ("hue", "CAP_PROP_HUE", config.hue),
        ("gamma", "CAP_PROP_GAMMA", config.gamma),
        ("sharpness", "CAP_PROP_SHARPNESS", config.sharpness),
        ("backlight", "CAP_PROP_BACKLIGHT", config.backlight),
        ("auto_white_balance", "CAP_PROP_AUTO_WB", config.auto_white_balance),
        (
            "white_balance_temperature",
            "CAP_PROP_WB_TEMPERATURE",
            config.white_balance_temperature,
        ),
        (
            "white_balance_blue",
            "CAP_PROP_WHITE_BALANCE_BLUE_U",
            config.white_balance_blue,
        ),
        (
            "white_balance_red",
            "CAP_PROP_WHITE_BALANCE_RED_V",
            config.white_balance_red,
        ),
        ("autofocus", "CAP_PROP_AUTOFOCUS", config.autofocus),
        ("focus", "CAP_PROP_FOCUS", config.focus),
        ("zoom", "CAP_PROP_ZOOM", config.zoom),
        ("pan", "CAP_PROP_PAN", config.pan),
        ("tilt", "CAP_PROP_TILT", config.tilt),
        ("roll", "CAP_PROP_ROLL", config.roll),
        ("buffer_size", "CAP_PROP_BUFFERSIZE", config.buffer_size),
    ]

    if config.verbose:
        defaults = []
        for label, constant, _ in settings:
            if hasattr(cv2_module, constant):
                default = _read_camera_property(capture, constant, cv2_module)
                defaults.append(f"{label}={default:g}")
        if hasattr(cv2_module, "CAP_PROP_FOURCC"):
            fourcc_value = _read_camera_property(capture, "CAP_PROP_FOURCC", cv2_module)
            defaults.append(f"fourcc={_format_fourcc(fourcc_value)}")
        defaults.extend(_read_diagnostics(capture, cv2_module))
        print("Camera defaults: " + ", ".join(defaults))

    for label, constant, value in settings:
        if value is not None:
            _set_and_verify(capture, cv2_module, label, constant, float(value), config.verbose)

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
            config.verbose,
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
    verbose: bool,
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
    if label == "fourcc":
        applied = int(actual) == int(requested)
    elif label == "fps":
        applied = math.isclose(actual, requested, rel_tol=_SETTING_TOLERANCE, abs_tol=0.5)
    else:
        applied = math.isclose(actual, requested, abs_tol=0.5)
    if not applied:
        raise CaptureError(
            f"Camera did not apply {label}: requested={requested_display or f'{requested:g}'} "
            f"actual={_format_fourcc(actual) if label == 'fourcc' else f'{actual:g}'}"
        )
    if verbose:
        print(
            f"Camera setting verified: {label}="
            f"{requested_display or f'{requested:g}'} (actual={_format_fourcc(actual) if label == 'fourcc' else f'{actual:g}'})"
        )


def _format_fourcc(value: float) -> str:
    encoded = int(value)
    text = "".join(chr((encoded >> shift) & 0xFF) for shift in (0, 8, 16, 24))
    return text if text.isprintable() and text.strip("\x00") else str(encoded)


def build_gstreamer_pipeline(config: CaptureConfig) -> str:
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

        pipeline_text = build_gstreamer_pipeline(config)
        if config.verbose:
            print(f"GStreamer pipeline: {pipeline_text}")
        try:
            pipeline = Gst.parse_launch(pipeline_text)
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
    ) -> None:
        apply_camera_settings(capture, config, cv2_module)


class NativeGStreamerBackend:
    def open(self, config: CaptureConfig, cv2_module: Any) -> CaptureHandle:
        del cv2_module
        return NativeGStreamerCapture(config)

    def configure(
        self,
        capture: CaptureHandle,
        config: CaptureConfig,
        cv2_module: Any,
    ) -> None:
        del capture, config, cv2_module


def create_capture_backend(name: str) -> CaptureBackend:
    backend = normalize_backend(name)
    if backend == "opencv":
        return OpenCvBackend()
    return NativeGStreamerBackend()


@contextmanager
def open_camera(
    config: CaptureConfig,
    cv2_module: Any,
    backend: CaptureBackend,
) -> Iterator[CaptureHandle]:
    capture = backend.open(config, cv2_module)
    try:
        if not capture.isOpened():
            raise CaptureError(camera_open_error(config.camera_index))
        backend.configure(capture, config, cv2_module)
        yield capture
    finally:
        try:
            capture.release()
        except Exception:
            pass
