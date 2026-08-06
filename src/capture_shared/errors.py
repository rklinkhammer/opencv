"""Typed domain errors shared by camera and GPIO capture workflows."""


class CaptureError(Exception):
    pass


class ConfigurationError(CaptureError):
    pass


class GpioError(CaptureError):
    pass
