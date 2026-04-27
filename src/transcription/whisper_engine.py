import numpy as np
from faster_whisper import WhisperModel
from src.utils.config import config
from src.utils.logger import log

_model: WhisperModel | None = None


def get_model() -> WhisperModel:
    global _model
    if _model is None:
        log.info(f"Loading Whisper model: {config.whisper_model}")
        _model = WhisperModel(config.whisper_model, device="cpu", compute_type="int8")
        log.info("Whisper model loaded")
    return _model


def transcribe(audio: np.ndarray) -> str:
    if len(audio) < config.sample_rate * 0.5:  # skip < 0.5s
        return ""

    model = get_model()
    segments, info = model.transcribe(
        audio,
        beam_size=5,
        language="en",
        vad_filter=False,  # we do our own VAD
    )

    text_parts = []
    for seg in segments:
        text = seg.text.strip()
        if text and seg.avg_logprob > -1.0:  # confidence filter
            text_parts.append(text)

    result = " ".join(text_parts)
    if result:
        log.debug(f"Transcribed: {result[:80]}...")
    return result
