class Errors:
    NO_ERROR: int = 0
    UNSUPPORTED_VERSION: int = 35


class WireProtocol:
    # Byte size sonstants
    MESSAGE_SIZE_BYTES = 4
    CORRRELATION_ID_BYTES = 4
    REQUEST_API_KEY_BYTES = 2
    REQUEST_API_VERSION_BYTES = 2
    TIME_BYTES = 4
    LENGTH_BYTES = 1
    TAG_BUFFER_BYTES = 1
    ERROR_BYTES = 2


def bytes_to_int(data: bytes) -> int:
    return int.from_bytes(data, "big")


def int_to_bytes(number: int, size: int) -> bytes:
    return number.to_bytes(size, "big")
