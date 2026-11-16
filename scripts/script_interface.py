from abc import ABC, abstractmethod

class ScriptInterface(ABC):
    """未来脚本插件接口。仅定义接口，不包含任何具体游戏脚本。"""
    @abstractmethod
    def metadata(self): pass
    @abstractmethod
    def initialize(self, context): pass
    @abstractmethod
    def execute(self, context, reporter): pass
    @abstractmethod
    def request_stop(self): pass
