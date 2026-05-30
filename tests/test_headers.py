from tests.conftest import make_buffer
from app.messages import ApiRequest, ApiResponse
from app.messages.headers import RequestHeader, ResponseHeaderV0, ResponseHeaderV1
from app.protocol import int_to_bytes, WireProtocol


def build_request_header_v2_bytes(
    api_key: int = 18,
    api_version: int = 4,
    correlation_id: int = 42,
    client_id: bytes = b"test-client",
) -> bytes:
    # RequestHeaderV2
    return (
        int_to_bytes(api_key, WireProtocol.REQUEST_API_KEY_BYTES)
        + int_to_bytes(api_version, WireProtocol.REQUEST_API_VERSION_BYTES)
        + int_to_bytes(correlation_id, WireProtocol.CORRRELATION_ID_BYTES)
        + int_to_bytes(len(client_id), WireProtocol.CLIENT_ID_BYTES)
        + client_id
        + b"\x00"  # tag_buffer
    )


class _ConcreteRequest(ApiRequest):
    def get_header(self):
        return self.read_header_flexible()

    def get_body(self):
        return None


class _NonFlexibleRequest(ApiRequest):
    def get_header(self):
        return self.read_header()

    def get_body(self):
        return None


def build_request_header_v1_bytes(
    api_key: int = 18,
    api_version: int = 4,
    correlation_id: int = 42,
    client_id: bytes = b"test-client",
) -> bytes:
    # RequestHeaderV1 — no tag buffer
    return (
        int_to_bytes(api_key, WireProtocol.REQUEST_API_KEY_BYTES)
        + int_to_bytes(api_version, WireProtocol.REQUEST_API_VERSION_BYTES)
        + int_to_bytes(correlation_id, WireProtocol.CORRRELATION_ID_BYTES)
        + int_to_bytes(len(client_id), WireProtocol.CLIENT_ID_BYTES)
        + client_id
    )


class TestRequestHeaderParsing:
    def test_api_key_parsed(self):
        raw = build_request_header_v2_bytes(api_key=18)
        req = _ConcreteRequest(make_buffer(raw))
        assert req.header.api_key == int_to_bytes(18, 2)

    def test_api_version_parsed(self):
        raw = build_request_header_v2_bytes(api_version=4)
        req = _ConcreteRequest(make_buffer(raw))
        assert req.header.api_version == int_to_bytes(4, 2)

    def test_correlation_id_parsed(self):
        raw = build_request_header_v2_bytes(correlation_id=99)
        req = _ConcreteRequest(make_buffer(raw))
        assert req.header.correlation_id == int_to_bytes(99, 4)

    def test_client_id_parsed(self):
        raw = build_request_header_v2_bytes(client_id=b"my-client")
        req = _ConcreteRequest(make_buffer(raw))
        assert req.header.client_id == b"my-client"

    def test_tag_buffer_parsed(self):
        raw = build_request_header_v2_bytes()
        req = _ConcreteRequest(make_buffer(raw))
        assert req.header.tag_buffer == b"\x00"

    def test_get_bytes_contains_all_fields(self):
        client_id = b"cli"
        raw = build_request_header_v2_bytes(
            api_key=18, api_version=4, correlation_id=42, client_id=client_id
        )
        req = _ConcreteRequest(make_buffer(raw))
        reassembled = req.header.get_bytes()
        # get_bytes() stores the raw bytes as parsed (client_id without its length prefix)
        assert int_to_bytes(18, 2) in reassembled
        assert int_to_bytes(42, 4) in reassembled
        assert client_id in reassembled


class TestResponseHeaderV0:
    def test_get_bytes_returns_correlation_id(self):
        corr = b"\x00\x00\x00\x2a"
        h = ResponseHeaderV0(corr)
        assert h.get_bytes() == corr

    def test_get_bytes_arbitrary(self):
        corr = b"\xde\xad\xbe\xef"
        h = ResponseHeaderV0(corr)
        assert h.get_bytes() == b"\xde\xad\xbe\xef"


class TestResponseHeaderV1:
    def test_get_bytes_concatenates(self):
        corr = b"\x00\x00\x00\x01"
        tag = b"\x00"
        h = ResponseHeaderV1(corr, tag)
        assert h.get_bytes() == corr + tag

    def test_length(self):
        h = ResponseHeaderV1(b"\x00\x00\x00\x05", b"\x00")
        assert len(h.get_bytes()) == 5


class TestNonFlexibleRequestHeader:
    def test_api_key_parsed(self):
        raw = build_request_header_v1_bytes(api_key=1)
        req = _NonFlexibleRequest(make_buffer(raw))
        assert req.header.api_key == int_to_bytes(1, 2)

    def test_correlation_id_parsed(self):
        raw = build_request_header_v1_bytes(correlation_id=7)
        req = _NonFlexibleRequest(make_buffer(raw))
        assert req.header.correlation_id == int_to_bytes(7, 4)

    def test_tag_buffer_defaults_to_zero(self):
        raw = build_request_header_v1_bytes()
        req = _NonFlexibleRequest(make_buffer(raw))
        assert req.header.tag_buffer == b"\x00"

    def test_client_id_parsed(self):
        raw = build_request_header_v1_bytes(client_id=b"kfk")
        req = _NonFlexibleRequest(make_buffer(raw))
        assert req.header.client_id == b"kfk"


class TestApiResponse:
    def test_get_bytes_concatenates_header_and_body(self):
        class _Chunk:
            def __init__(self, data): self._data = data
            def get_bytes(self): return self._data

        class _Resp(ApiResponse):
            pass

        resp = _Resp()
        resp.header = _Chunk(b"\x00\x00\x00\x01\x00")
        resp.body = _Chunk(b"\xff\xff")
        assert resp.get_bytes() == b"\x00\x00\x00\x01\x00\xff\xff"

    def test_get_size_matches_bytes_length(self):
        class _Chunk:
            def __init__(self, data): self._data = data
            def get_bytes(self): return self._data

        class _Resp(ApiResponse):
            pass

        resp = _Resp()
        resp.header = _Chunk(b"\x00\x00\x00\x05\x00")
        resp.body = _Chunk(b"\x01\x02\x03")
        assert resp.get_size() == 8
