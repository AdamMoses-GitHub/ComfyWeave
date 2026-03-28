"""
ComfyWeave — PySide6 desktop client for ComfyUI
Entry point: python main.py

Environment variable overrides (useful for launch configs / CI):
  COMFYUI_SERVER       Override server URL  (e.g. http://192.168.1.10:8188)
  COMFYUI_AUTO_CONNECT Set to "1" to auto-connect on startup
  COMFYUI_THEME        Override theme: "dark" or "light"
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Python 3.8+ on Windows no longer uses PATH for DLL resolution — it requires
# os.add_dll_directory().  We also set QT_QPA_PLATFORM_PLUGIN_PATH explicitly
# because PySide6 can't discover its own plugins when launched via the VS Code
# debugger without a fully activated conda environment.
try:
    import importlib.util as _ilu
    _pyside6_spec = _ilu.find_spec("PySide6")
    if _pyside6_spec and _pyside6_spec.origin:
        _pyside6_dir = Path(_pyside6_spec.origin).parent
        # Register DLL search directory (Python 3.8+ mechanism)
        os.add_dll_directory(str(_pyside6_dir))
        # Tell Qt where to find platform plugins (qwindows.dll etc.)
        _plugins_dir = str(_pyside6_dir / "plugins" / "platforms")
        if not os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH"):
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = _plugins_dir
    del _ilu, _pyside6_spec, _pyside6_dir, _plugins_dir
except Exception:
    pass

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

try:
    import qasync
except ImportError:
    print(
        "qasync is not installed. Run:  pip install -r requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)

from utils.config_manager import ConfigManager
from ui.main_window import MainWindow, _apply_theme


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("ComfyWeave")
    app.setOrganizationName("ComfyWeave")

    # Application icon (window chrome + taskbar)
    _icon_path = Path(__file__).parent / "assets" / "icon.png"
    if _icon_path.exists():
        app.setWindowIcon(QIcon(str(_icon_path)))

    # Load persisted settings
    cfg_mgr = ConfigManager()
    cfg_mgr.load()

    # Apply environment variable overrides (non-persistent — only for this session)
    if server := os.environ.get("COMFYUI_SERVER"):
        cfg_mgr.config.server_url = server
    if os.environ.get("COMFYUI_AUTO_CONNECT") == "1":
        cfg_mgr.config.auto_connect = True
    if theme := os.environ.get("COMFYUI_THEME"):
        cfg_mgr.config.theme = theme

    # Apply initial theme
    _apply_theme(cfg_mgr.config.theme)

    # Install qasync event loop so asyncio works inside Qt
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow(cfg_mgr)
    window.show()

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
