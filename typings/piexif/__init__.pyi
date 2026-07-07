class ImageIFD:
    DateTime: int

class ExifIFD:
    DateTimeOriginal: int
    DateTimeDigitized: int
    OffsetTime: int
    OffsetTimeOriginal: int
    OffsetTimeDigitized: int

def dump(exif_dict: dict[str, dict[int, bytes]]) -> bytes: ...
def insert(exif_bytes: bytes, filename: str) -> None: ...
