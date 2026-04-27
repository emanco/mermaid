import sounddevice as sd
from src.utils.config import config
from src.utils.logger import log


def find_device(name_fragment: str) -> dict | None:
    for dev in sd.query_devices():
        if name_fragment.lower() in dev["name"].lower() and dev["max_input_channels"] > 0:
            return dev
    return None


def get_mic_device() -> dict:
    dev = find_device(config.mic_device_name)
    if dev is None:
        log.warning(f"'{config.mic_device_name}' not found, falling back to system default mic")
        default_idx = sd.default.device[0]
        dev = sd.query_devices(default_idx)
    log.info(f"Mic device: {dev['name']}")
    return dev


def get_blackhole_device() -> dict:
    dev = find_device(config.blackhole_device_name)
    if dev is None:
        log.error("BlackHole not found. Install with: brew install blackhole-2ch")
        log.error("Then create a Multi-Output Device in Audio MIDI Setup.")
        raise RuntimeError("BlackHole audio device not found")
    log.info(f"BlackHole device: {dev['name']}")
    return dev


def list_devices():
    log.info("Available audio input devices:")
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            log.info(f"  [{i}] {dev['name']} ({dev['max_input_channels']}ch, {dev['default_samplerate']}Hz)")
