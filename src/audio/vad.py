import numpy as np
import torch
from src.utils.config import config
from src.utils.logger import log


class VoiceActivityDetector:
    def __init__(self):
        self.model, self.utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
        )
        self._buffer = np.array([], dtype=np.float32)
        self._speech_active = False
        self._speech_start_samples = 0
        self._window_size = 512  # Silero VAD expects 512 samples at 16kHz

    def reset(self):
        self._buffer = np.array([], dtype=np.float32)
        self._speech_active = False
        self.model.reset_states()

    def process(self, audio_chunk: np.ndarray) -> list[np.ndarray]:
        self._buffer = np.concatenate([self._buffer, audio_chunk])
        segments = []

        while len(self._buffer) >= self._window_size:
            window = self._buffer[:self._window_size]
            self._buffer = self._buffer[self._window_size:]

            tensor = torch.from_numpy(window)
            prob = self.model(tensor, config.sample_rate).item()

            if prob >= config.vad_threshold and not self._speech_active:
                self._speech_active = True
                self._speech_start_samples = 0
                self._speech_buffer = [window]
            elif self._speech_active:
                self._speech_buffer.append(window)
                self._speech_start_samples += self._window_size
                duration = self._speech_start_samples / config.sample_rate

                if prob < config.vad_threshold:
                    if duration >= config.min_speech_duration:
                        segment = np.concatenate(self._speech_buffer)
                        segments.append(segment)
                    self._speech_active = False
                    self._speech_buffer = []
                elif duration >= config.max_speech_duration:
                    segment = np.concatenate(self._speech_buffer)
                    segments.append(segment)
                    self._speech_active = False
                    self._speech_buffer = []

        return segments
