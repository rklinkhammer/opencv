"""Open and release camera handles."""

from __future__ import annotations

from typing import Any

from capture_shared.errors import CameraOpenError

from .backends import CaptureBackend, CaptureHandle
from .models import CaptureConfig
from .validators import camera_open_error


def safe_release(capture: CaptureHandle) -> None:
    try:
        capture.release()
    except Exception:  # pragma: no cover - defensive cleanup
        pass


class CameraSession:
    def __init__(
        self,
        config: CaptureConfig,
        cv2_module: Any,
        backend: CaptureBackend,
    ) -> None:
        self._config = config
        self._cv2_module = cv2_module
        self._backend = backend
        self._capture: CaptureHandle | None = None

    def __enter__(self) -> CaptureHandle:
        capture = self._backend.open(self._config, self._cv2_module)
        self._capture = capture
        try:
            if not capture.isOpened():
                raise CameraOpenError(camera_open_error(self._config.camera_index))
            self._backend.configure(capture, self._config, self._cv2_module)
            return capture
        except Exception:
            safe_release(capture)
            self._capture = None
            raise

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._capture is not None:
            safe_release(self._capture)
            self._capture = None
