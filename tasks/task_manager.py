class TaskManager:
    """任务管理框架占位：负责任务登记、状态与调度，不执行游戏内流程。"""
    def __init__(self):
        self.tasks = {}
    def register(self, task_id, task_meta):
        self.tasks[task_id] = {"meta": task_meta, "status": "待配置"}
    def list_tasks(self):
        return [{"id":k, **v} for k,v in self.tasks.items()]
