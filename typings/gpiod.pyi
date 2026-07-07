from typing import Any

LINE_REQ_EV_RISING_EDGE: int
LINE_REQ_EV_FALLING_EDGE: int
LINE_REQ_EV_BOTH_EDGES: int
LINE_REQ_FLAG_EVENT_CLOCK_REALTIME: int
line: Any

class Chip:
    def __init__(self, name: str) -> None: ...
    def get_line(self, offset: int) -> Any: ...
    def close(self) -> None: ...

class LineSettings:
    def __init__(self, **kwargs: Any) -> None: ...

def request_lines(*args: Any, **kwargs: Any) -> Any: ...
