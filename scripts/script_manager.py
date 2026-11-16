from pathlib import Path

class ScriptManager:
    """脚本管理占位：扫描插件元信息；默认不自动导入或执行未知代码。"""
    def __init__(self, plugin_dir=None):
        self.plugin_dir = Path(plugin_dir) if plugin_dir else Path(__file__).parent / "plugins"
    def list_plugins(self):
        self.plugin_dir.mkdir(parents=True, exist_ok=True)
        return [{"name":p.name, "status":"未加载（预留）"} for p in self.plugin_dir.iterdir() if p.is_dir()]
