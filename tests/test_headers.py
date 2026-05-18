from tests.conftest import make_buffer
from app.messages import ApiRequest
from app.messages.headers import ResponseHeaderV0, ResponseHeaderV1
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
