"""Typed domain errors shared by camera and GPIO capture workflows."""


class CaptureSystemError(Exception):
    """Base class for known camera/GPIO capture package failures."""


class ConfigurationError(CaptureSystemError):
    """Raised when package configuration is invalid."""


class BackendError(CaptureSystemError):
    """Raised when a capture backend cannot be initialized."""


class CameraOpenError(BackendError):
    """Raised when a configured camera handle cannot be opened."""


class WriterError(CaptureSystemError):
    """Raised when an image writer cannot persist a frame."""


class WriterTimeoutError(WriterError):
    """Raised when a writer cannot stop before its shutdown deadline."""


class OutputError(CaptureSystemError):
    """Raised when capture output cannot be reserved or committed."""


class GpioError(CaptureSystemError):
    """Raised when GPIO bindings, chips, lines, or requests cannot be set up."""


class ParallelExecutionError(CaptureSystemError):
    """Raised when a parallel worker does not report a valid completion."""
