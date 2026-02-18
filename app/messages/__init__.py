from abc import abstractmethod
from typing import Protocol

from app.connection import Buffer


class ApiRequest(Protocol):
    def __init__(self, buffer: Buffer):
        self.buffer = buffer

    @abstractmethod
    def get_header(self):
        pass

    @abstractmethod
    def get_body(self):
        pass


class ApiResponse(Protocol):
    pass
