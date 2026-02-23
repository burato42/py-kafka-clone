from dataclasses import dataclass

from app.connection import Buffer

def read_cluster_metadata_log(buffer: Buffer) -> ClusterMetadataLogFile:
    raise NotImplementedError


@dataclass
class ClusterMetadataLogFile:
    raise NotImplementedError
