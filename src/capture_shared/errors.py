"""Typed domain errors shared by camera and GPIO capture workflows."""


class CaptureSystemError(Exception):
    pass


class ConfigurationError(CaptureSystemError):
    pass


class BackendError(CaptureSystemError):
    pass


class CameraOpenError(BackendError):
    pass


class WriterError(CaptureSystemError):
    pass


class WriterTimeoutError(WriterError):
    pass


class OutputError(CaptureSystemError):
    pass


class GpioError(CaptureSystemError):
    pass


class ParallelExecutionError(CaptureSystemError):
    pass
