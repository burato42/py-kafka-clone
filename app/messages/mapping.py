from app.messages import ApiRequest
from app.messages.api_version import ApiVersionRequest

APIKEYS: dict[int, type[ApiRequest]] = {18: ApiVersionRequest}
