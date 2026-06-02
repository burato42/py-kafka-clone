from app.messages import ApiRequest
from app.messages.api_key import ApiKeyConstants
from app.messages.api_version import ApiVersionRequest
from app.messages.describe_topic_part import DescribeTopicPartitionsRequest
from app.messages.fetch import FetchRequest
from app.messages.init_producer_id import InitProducerIdRequest
from app.messages.list_offsets import ListOffsetsRequest
from app.messages.metadata import MetadataRequest
from app.messages.produce import ProduceRequest

APIKEYS: dict[int, type[ApiRequest]] = {
    ApiKeyConstants.API_VERSION: ApiVersionRequest,
    ApiKeyConstants.DESCRIBE_TOPIC_PARTITION: DescribeTopicPartitionsRequest,
    ApiKeyConstants.FETCH: FetchRequest,
    ApiKeyConstants.INIT_PRODUCER_ID: InitProducerIdRequest,
    ApiKeyConstants.LIST_OFFSETS: ListOffsetsRequest,
    ApiKeyConstants.METADATA: MetadataRequest,
    ApiKeyConstants.PRODUCE: ProduceRequest,
}
