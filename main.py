
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

# 确保项目根目录在 Python 搜索路径中
PROJECT_DIR = Path(__file__).resolve().parent

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from ui.startup_window import StartupWindow
from core.config import load_config


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("雷电模拟器局域网中控")
    app.setStyle("Fusion")

    cfg = load_config()

    window = StartupWindow(cfg)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
