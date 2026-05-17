class ResponseHeaderV0:
    def __init__(self, correlation_id: bytes):
        self.correlation_id = correlation_id

    def get_bytes(self):
        return self.correlation_id


class ResponseHeaderV1:
    def __init__(self, correlation_id: bytes, tag_buffer: bytes):
        self.correlation_id = correlation_id
        self.tag_buffer = tag_buffer

    def get_bytes(self):
        return b"".join([self.correlation_id, self.tag_buffer])


class RequestHeader:
    def __init__(
        self,
        api_key: bytes,
        api_version: bytes,
        correlation_id: bytes,
        client_id: bytes,
        tag_buffer: bytes,
    ):
        self.api_key = api_key
        self.api_version = api_version
        self.correlation_id = correlation_id
        self.client_id = client_id
        self.tag_buffer = tag_buffer

    def get_bytes(self) -> bytes:
        return b"".join(
            [
                self.api_key,
                self.api_version,
                self.correlation_id,
                self.client_id,
                self.tag_buffer,
            ]
        )
