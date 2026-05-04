from app.messages import ApiRequest
from app.messages.api_key import ApiKeyConstants
from app.messages.api_version import ApiVersionRequest
from app.messages.describe_topic_part import DescribeTopicPartitionsRequest
from app.messages.fetch import FetchRequest

APIKEYS: dict[int, type[ApiRequest]] = {
    ApiKeyConstants.API_VERSION: ApiVersionRequest,
    ApiKeyConstants.DESCRIBE_TOPIC_PARTITION: DescribeTopicPartitionsRequest,
    ApiKeyConstants.FETCH: FetchRequest,
}
