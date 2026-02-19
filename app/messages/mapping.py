from app.messages import ApiRequest
from app.messages.api_key import ApiKeyConstants
from app.messages.api_version import ApiVersionRequest

APIKEYS: dict[int, type[ApiRequest]] = {ApiKeyConstants.API_VERSION: ApiVersionRequest}
