import subprocess
from pathlib import Path

def adb_screenshot(serial, output_path, adb_path="adb"):
    """从指定 ADB serial 截图；需设备已连接且已授权。"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([adb_path, "-s", serial, "exec-out", "screencap", "-p"],
                            capture_output=True, timeout=20)
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(result.stderr.decode("utf-8", "replace") or "ADB 截图失败")
    output_path.write_bytes(result.stdout)
    return str(output_path)
