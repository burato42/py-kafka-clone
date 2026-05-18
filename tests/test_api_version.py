from tests.conftest import make_buffer
from app.messages.api_version import ApiVersionRequest, handle_api_version_request
from app.protocol import int_to_bytes, bytes_to_int, WireProtocol, Errors


def build_api_version_request_bytes(
    api_version: int = 4,
    correlation_id: int = 1,
    header_client_id: bytes = b"kafka-cli",
    body_client_id: bytes = b"my-app",
    software_version: bytes = b"1.0.0",
) -> bytes:
    # RequestHeader
    header = (
        int_to_bytes(18, WireProtocol.REQUEST_API_KEY_BYTES)  # api_key=18 (API_VERSION)
        + int_to_bytes(api_version, WireProtocol.REQUEST_API_VERSION_BYTES)
        + int_to_bytes(correlation_id, WireProtocol.CORRRELATION_ID_BYTES)
        + int_to_bytes(len(header_client_id), WireProtocol.CLIENT_ID_BYTES)
        + header_client_id
        + b"\x00"  # tag_buffer
    )
    # Body: compact string encoding — length prefix is len+1 (uvarint)
    body = (
        bytes([len(body_client_id) + 1])
        + body_client_id
        + bytes([len(software_version) + 1])
        + software_version
        + b"\x00"  # tag_buffer
    )
    return header + body


class TestApiVersionRequestParsing:
    def test_header_api_key(self):
        raw = build_api_version_request_bytes(api_version=4)
        req = ApiVersionRequest(make_buffer(raw))
        assert req.header.api_key == int_to_bytes(18, 2)

    def test_header_api_version(self):
        raw = build_api_version_request_bytes(api_version=4)
        req = ApiVersionRequest(make_buffer(raw))
        assert bytes_to_int(req.header.api_version) == 4

    def test_header_correlation_id(self):
        raw = build_api_version_request_bytes(correlation_id=77)
        req = ApiVersionRequest(make_buffer(raw))
        assert bytes_to_int(req.header.correlation_id) == 77

    def test_body_client_id(self):
        raw = build_api_version_request_bytes(body_client_id=b"test-app")
        req = ApiVersionRequest(make_buffer(raw))
        assert req.body.client_id == b"test-app"

    def test_body_software_version(self):
        raw = build_api_version_request_bytes(software_version=b"2.3.1")
        req = ApiVersionRequest(make_buffer(raw))
        assert req.body.client_software_version == b"2.3.1"


class TestHandleApiVersionRequest:
    def _make_request(self, api_version: int) -> ApiVersionRequest:
        raw = build_api_version_request_bytes(api_version=api_version)
        return ApiVersionRequest(make_buffer(raw))

    def _parse_response_body(self, response_bytes: bytes):
        """Parse the raw response bytes: skip 4-byte size, 4-byte correlation_id."""
        # response bytes = header.get_bytes() + body.get_bytes()
        # ResponseHeaderV0 = 4 bytes (correlation_id)
        error = bytes_to_int(response_bytes[4:6])
        return error

    def test_valid_version_returns_no_error(self):
        req = self._make_request(api_version=4)
        resp = handle_api_version_request(req)
        body_bytes = resp.body.get_bytes()
        error = bytes_to_int(body_bytes[:2])
        assert error == Errors.NO_ERROR

    def test_valid_version_returns_api_keys(self):
        req = self._make_request(api_version=4)
        resp = handle_api_version_request(req)
        assert len(resp.body.api_keys) > 0

    def test_invalid_version_returns_unsupported_version(self):
        req = self._make_request(api_version=99)
        resp = handle_api_version_request(req)
        body_bytes = resp.body.get_bytes()
        error = bytes_to_int(body_bytes[:2])
        assert error == Errors.UNSUPPORTED_VERSION

    def test_invalid_version_returns_no_api_keys(self):
        req = self._make_request(api_version=99)
        resp = handle_api_version_request(req)
        assert resp.body.api_keys == []

    def test_version_zero_is_valid(self):
        req = self._make_request(api_version=0)
        resp = handle_api_version_request(req)
        body_bytes = resp.body.get_bytes()
        assert bytes_to_int(body_bytes[:2]) == Errors.NO_ERROR

    def test_version_11_is_valid(self):
        req = self._make_request(api_version=11)
        resp = handle_api_version_request(req)
        body_bytes = resp.body.get_bytes()
        assert bytes_to_int(body_bytes[:2]) == Errors.NO_ERROR

    def test_version_12_is_invalid(self):
        req = self._make_request(api_version=12)
        resp = handle_api_version_request(req)
        body_bytes = resp.body.get_bytes()
        assert bytes_to_int(body_bytes[:2]) == Errors.UNSUPPORTED_VERSION

    def test_response_correlation_id_matches_request(self):
        raw = build_api_version_request_bytes(api_version=4, correlation_id=42)
        req = ApiVersionRequest(make_buffer(raw))
        resp = handle_api_version_request(req)
        header_bytes = resp.header.get_bytes()
        assert bytes_to_int(header_bytes[:4]) == 42

    def test_get_size_matches_get_bytes_length(self):
        req = self._make_request(api_version=4)
        resp = handle_api_version_request(req)
        assert resp.get_size() == len(resp.get_bytes())
