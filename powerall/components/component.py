from abc import ABCMeta, abstractmethod


class Component:
    @abstractmethod
    def __init__(self):
        pass

    @abstractmethod
    def __enter__(self):
        pass

    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def setup(self):
        pass

    @abstractmethod
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    @abstractmethod
    def get_attrs(self, argl):
        pass

    @abstractmethod
    def update(self) -> bytes:
        pass

    @abstractmethod
    def control(self, argl):
        pass
