
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import load_config, save_config


CONSOLE_NAME = "dnconsole.exe"
_cached_console = None


def _decode_output(data):
    """兼容雷电命令行的 UTF-8、GBK 中文输出。"""
    if not data:
        return ""

    if isinstance(data, str):
        return data.strip()

    for encoding in ("utf-8-sig", "gbk", "utf-8"):
        try:
            return data.decode(encoding).strip()
        except UnicodeDecodeError:
            continue

    return data.decode("gbk", errors="replace").strip()


def choose_console_path(parent=None):
    """选择 dnconsole.exe。"""
    global _cached_console

    from PySide6.QtWidgets import QFileDialog, QMessageBox

    path, _ = QFileDialog.getOpenFileName(
        parent,
        "选择雷电模拟器命令行程序",
        "",
        "雷电命令行程序 (dnconsole.exe);;EXE 文件 (*.exe)"
    )

    if not path:
        return None

    target = Path(path)

    if target.name.lower() != CONSOLE_NAME.lower():
        QMessageBox.warning(
            parent,
            "文件选择错误",
            "请选择 dnconsole.exe。"
        )
        return None

    if not target.is_file():
        QMessageBox.warning(
            parent,
            "文件不存在",
            "选择的文件不存在，请重新选择。"
        )
        return None

    target = target.resolve()

    cfg = load_config()
    cfg["ldconsole_path"] = str(target)
    save_config(cfg)

    _cached_console = str(target)

    QMessageBox.information(
        parent,
        "保存成功",
        f"雷电模拟器路径已保存：\n{target}"
    )

    return str(target)


def get_console_path():
    cfg = load_config()
    return str(cfg.get("ldconsole_path", "") or "").strip()


def find_console():
    global _cached_console

    if _cached_console:
        cached = Path(_cached_console)
        if cached.is_file():
            return cached

    configured_path = get_console_path()

    if not configured_path:
        raise FileNotFoundError(
            "尚未选择雷电模拟器 dnconsole.exe，"
            "请在辅助端设置中选择文件。"
        )

    console = Path(configured_path)

    if not console.is_file():
        raise FileNotFoundError(
            f"雷电模拟器文件不存在：{console}"
        )

    if console.name.lower() != CONSOLE_NAME.lower():
        raise ValueError("保存的文件不是 dnconsole.exe")

    _cached_console = str(console.resolve())
    return Path(_cached_console)


def _run_console_command(*args, timeout=30):
    """执行雷电命令，并兼容中文编码。"""
    console = find_console()

    try:
        result = subprocess.run(
            [str(console), *[str(arg) for arg in args]],
            capture_output=True,
            text=False,
            timeout=timeout,
            creationflags=getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0
            ),
        )

    except OSError as exc:
        if getattr(exc, "winerror", None) == 740:
            raise PermissionError(
                "雷电模拟器要求管理员权限。"
                "请关闭中控程序，使用管理员身份重新运行。"
            ) from exc

        raise RuntimeError(
            f"调用雷电模拟器失败：{exc}"
        ) from exc

    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"雷电命令执行超时：{args}"
        ) from exc

    stdout = _decode_output(result.stdout)
    stderr = _decode_output(result.stderr)

    if result.returncode != 0:
        raise RuntimeError(
            f"雷电命令执行失败：{stderr or stdout or result.returncode}"
        )

    return subprocess.CompletedProcess(
        result.args,
        result.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def list_emulators():
    """读取雷电多开器中的模拟器列表。"""
    result = _run_console_command(
        "list2",
        timeout=30
    )

    emulators = []

    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        parts = [
            part.strip()
            for part in line.split(",")
        ]

        if len(parts) < 2:
            continue

        try:
            index = int(parts[0])
        except ValueError:
            continue

        name = parts[1] or f"雷电模拟器-{index}"

        started = False

        if len(parts) >= 5:
            started = parts[4] == "1"

        emulators.append({
            "index": index,
            "name": name,
            "started": started,
        })

    emulators.sort(
        key=lambda item: item["index"]
    )

    return emulators


def start_emulator(index):
    """启动指定编号的模拟器。"""
    return _run_console_command(
        "launch",
        "--index",
        index,
        timeout=60
    )


def quit_emulator(index):
    """关闭指定编号的模拟器。"""
    return _run_console_command(
        "quit",
        "--index",
        index,
        timeout=60
    )


def get_emulator_boot_status(index):
    """获取 Android 系统启动状态。"""
    result = _run_console_command(
        "adb",
        "--index",
        index,
        "--command",
        "shell getprop sys.boot_completed",
        timeout=15
    )

    output = result.stdout.strip()

    ready = any(
        line.strip() == "1"
        for line in output.splitlines()
    )

    return ready, output


def test_console():
    console = find_console()
    emulators = list_emulators()

    return {
        "success": True,
        "path": str(console),
        "emulators": emulators,
    }
