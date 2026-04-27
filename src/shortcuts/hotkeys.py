from pynput import keyboard
from src.utils.state import state
from src.utils.logger import log

_listener = None
_loop = None
_generate_callback = None


def _on_generate():
    state.request_regenerate()
    log.info("Diagram generation requested (Ctrl+Shift+M)")


def start_hotkeys():
    global _listener
    hotkeys = keyboard.GlobalHotKeys({
        "<ctrl>+<shift>+m": _on_generate,
    })
    hotkeys.daemon = True
    hotkeys.start()
    _listener = hotkeys
    log.info("Hotkey registered: Ctrl+Shift+M (generate diagram)")
    return hotkeys


def stop_hotkeys():
    global _listener
    if _listener:
        _listener.stop()
        _listener = None
