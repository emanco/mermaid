import queue
import numpy as np
import sounddevice as sd
from src.utils.config import config
from src.utils.logger import log


class AudioStream:
    def __init__(self, device_index: int, label: str):
        self.device_index = device_index
        self.label = label
        self.queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: sd.InputStream | None = None

        dev_info = sd.query_devices(device_index)
        self._native_rate = int(dev_info["default_samplerate"])

    def _callback(self, indata: np.ndarray, frames: int, time_info, status):
        if status:
            log.warning(f"[{self.label}] Audio status: {status}")
        audio = indata[:, 0].copy()  # mono
        if self._native_rate != config.sample_rate:
            audio = self._resample(audio, self._native_rate, config.sample_rate)
        self.queue.put(audio)

    @staticmethod
    def _resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
        if src_rate == dst_rate:
            return audio
        ratio = dst_rate / src_rate
        new_length = int(len(audio) * ratio)
        indices = np.linspace(0, len(audio) - 1, new_length)
        return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)

    def start(self):
        log.info(f"Starting audio stream: {self.label} (device {self.device_index}, native {self._native_rate}Hz)")
        self._stream = sd.InputStream(
            device=self.device_index,
            samplerate=self._native_rate,
            channels=1,
            dtype="float32",
            blocksize=config.chunk_frames,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
            log.info(f"Stopped audio stream: {self.label}")

    def get_chunks(self) -> list[np.ndarray]:
        chunks = []
        while not self.queue.empty():
            try:
                chunks.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return chunks
