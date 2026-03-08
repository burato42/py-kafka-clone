class Errors:
    NO_ERROR: int = 0
    UNSUPPORTED_VERSION: int = 35
    UNKNOWN_TOPIC_OR_PARTITION: int = 3

class ValueTypes:
    FEATURE_LEVEL_RECORD_VALUE: int = 12
    TOPIC_RECORD_VALUE: int = 2
    PARTITION_RECORD_VALUE: int = 3


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
    RESPONSE_PARTITION_LIMIT_BYTES = 4
    CURSOR_BYTES = 1
    TOPIC_ID_BYTES = 16
    BOOLEAN_BYTES = 1
    TOPIC_AUTH_OPS_BYTES = 4
    CLIENT_ID_BYTES = 2


def bytes_to_int(data: bytes) -> int:
    return int.from_bytes(data, "big")


def int_to_bytes(number: int, size: int) -> bytes:
    return number.to_bytes(size, "big")


def int_to_bytes_signed(number: int, size: int) -> bytes:
    return number.to_bytes(size, "big", signed=True)
