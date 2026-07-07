"""Backend adapters for OpenCV and native GStreamer frame ingestion."""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np

from capture_shared.errors import BackendError, ConfigurationError

from .models import CaptureConfig
from .validators import normalize_backend, normalize_fourcc

_GSTREAMER_SAMPLE_TIMEOUT_MILLISECONDS = 100


class CaptureHandle(Protocol):
    """Minimal camera handle shared by backend and session boundaries."""

    def isOpened(self) -> bool:
        """Return whether the underlying capture resource opened successfully."""

        ...

    def read(self) -> tuple[bool, Any]:
        """Return a success flag and the next frame payload."""

        ...

    def release(self) -> None:
        """Release hardware or pipeline resources owned by the handle."""

        ...


class CaptureBackend(Protocol):
    """Backend boundary for opening and configuring capture handles."""

    def open(self, config: CaptureConfig, cv2_module: Any) -> CaptureHandle:
        """Open and return a capture handle for the supplied configuration."""

        ...

    def configure(
        self,
        capture: CaptureHandle,
        config: CaptureConfig,
        cv2_module: Any,
    ) -> None:
        """Apply backend-specific configuration to an opened handle."""

        ...


def apply_camera_settings(
    capture: Any,
    config: CaptureConfig,
    cv2_module: Any,
) -> None:
    """Apply optional camera controls to an OpenCV capture object."""

    property_mappings: list[tuple[str, float | None, bool]] = [
        ("CAP_PROP_FPS", float(config.fps), True),
        (
            "CAP_PROP_FRAME_WIDTH",
            float(config.frame_width) if config.frame_width is not None else None,
            config.frame_width is not None,
        ),
        (
            "CAP_PROP_FRAME_HEIGHT",
            float(config.frame_height) if config.frame_height is not None else None,
            config.frame_height is not None,
        ),
        (
            "CAP_PROP_AUTO_EXPOSURE",
            float(config.auto_exposure) if config.auto_exposure is not None else None,
            config.auto_exposure is not None,
        ),
        (
            "CAP_PROP_EXPOSURE",
            float(config.exposure) if config.exposure is not None else None,
            config.exposure is not None,
        ),
        (
            "CAP_PROP_GAIN",
            float(config.gain) if config.gain is not None else None,
            config.gain is not None,
        ),
        (
            "CAP_PROP_BRIGHTNESS",
            float(config.brightness) if config.brightness is not None else None,
            config.brightness is not None,
        ),
    ]

    for prop_name, value, enabled in property_mappings:
        if not enabled or value is None:
            continue
        if not hasattr(cv2_module, prop_name):
            continue
        capture.set(getattr(cv2_module, prop_name), float(value))

    if (
        config.fourcc
        and hasattr(cv2_module, "CAP_PROP_FOURCC")
        and hasattr(cv2_module, "VideoWriter_fourcc")
    ):
        fourcc = normalize_fourcc(config.fourcc)
        assert fourcc is not None
        capture.set(cv2_module.CAP_PROP_FOURCC, cv2_module.VideoWriter_fourcc(*fourcc))


def build_gstreamer_pipeline(config: CaptureConfig) -> str:
    """Build a GStreamer pipeline string from source presets and config."""

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
    """Thin capture wrapper around a native GStreamer appsink pipeline."""

    def __init__(self, config: CaptureConfig):
        """Initialize pipeline, resolve appsink, and move to PLAYING state."""

        try:
            import gi

            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
        except ImportError as exc:
            raise BackendError(
                "Native GStreamer backend requires PyGObject. "
                "Install python3-gi and gir1.2-gstreamer-1.0."
            ) from exc

        self._Gst = Gst
        Gst.init(None)

        pipeline_text = build_gstreamer_pipeline(config)
        try:
            pipeline = Gst.parse_launch(pipeline_text)
        except Exception as exc:
            raise BackendError(f"Invalid GStreamer pipeline: {exc}") from exc

        appsink = pipeline.get_by_name("appsink")
        if appsink is None:
            raise BackendError(
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
        """Return whether the capture backend initialized successfully."""

        return self._opened

    def read(self) -> tuple[bool, Any]:
        """Read one BGR frame from appsink and return success flag + frame."""

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
        """Release GStreamer resources and set pipeline state to NULL."""

        self._pipeline.set_state(self._Gst.State.NULL)
        self._opened = False


class OpenCvBackend:
    """Open and configure captures through the injected OpenCV module."""

    def open(self, config: CaptureConfig, cv2_module: Any) -> CaptureHandle:
        """Open an OpenCV capture for the configured camera index."""

        return cv2_module.VideoCapture(config.camera_index)

    def configure(
        self,
        capture: CaptureHandle,
        config: CaptureConfig,
        cv2_module: Any,
    ) -> None:
        """Apply validated optional capture properties through OpenCV constants."""

        apply_camera_settings(capture, config, cv2_module)


class NativeGStreamerBackend:
    """Open native GStreamer captures whose pipeline owns configuration."""

    def open(self, config: CaptureConfig, cv2_module: Any) -> CaptureHandle:
        """Construct a native GStreamer appsink capture."""

        del cv2_module
        return NativeGStreamerCapture(config)

    def configure(
        self,
        capture: CaptureHandle,
        config: CaptureConfig,
        cv2_module: Any,
    ) -> None:
        """Perform no extra setup because configuration is in the pipeline."""

        del capture, config, cv2_module


def create_capture_backend(name: str) -> CaptureBackend:
    """Return the backend implementation for a normalized public backend name."""

    backend = normalize_backend(name)
    if backend == "opencv":
        return OpenCvBackend()
    return NativeGStreamerBackend()


def open_capture(config: CaptureConfig, cv2_module: Any) -> CaptureHandle:
    """Open a capture handle through the selected backend.

    This compatibility helper preserves the original public function while new
    orchestration code uses `create_capture_backend()` and `CameraSession`.
    """

    backend = create_capture_backend(config.capture_backend)
    return backend.open(config, cv2_module)
