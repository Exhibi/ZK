from pathlib import Path
import shutil

class TemplateManager:
    def __init__(self, root=None):
        self.root = Path(root) if root else Path(__file__).resolve().parent.parent/"templates"
        self.root.mkdir(parents=True, exist_ok=True)
    def import_template(self, source):
        src=Path(source)
        if not src.is_file(): raise FileNotFoundError(src)
        dst=self.root/src.name
        shutil.copy2(src,dst)
        return str(dst)
    def list_templates(self):
        return [p.name for p in self.root.iterdir() if p.is_file()]
