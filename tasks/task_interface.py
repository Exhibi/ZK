from abc import ABC, abstractmethod

class TaskInterface(ABC):
    """未来任务插件统一接口；本版本不提供具体游戏任务实现。"""
    @abstractmethod
    def validate(self, context): pass
    @abstractmethod
    def run(self, context, reporter): pass
    @abstractmethod
    def stop(self): pass
