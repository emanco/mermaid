from dataclasses import dataclass, field
from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@dataclass
class Config:
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    whisper_model: str = field(default_factory=lambda: os.getenv("WHISPER_MODEL", "base.en"))
    debounce_seconds: float = field(default_factory=lambda: float(os.getenv("DEBOUNCE_SECONDS", "8")))
    max_context_tokens: int = field(default_factory=lambda: int(os.getenv("MAX_CONTEXT_TOKENS", "6000")))
    min_context_chars_for_auto_draw: int = field(default_factory=lambda: int(os.getenv("MIN_CONTEXT_CHARS_FOR_AUTO_DRAW", "400")))
    render_backend: str = field(default_factory=lambda: os.getenv("RENDER_BACKEND", "mermaid_ink"))
    render_url: str = field(default_factory=lambda: os.getenv("RENDER_URL", "https://mermaid.ink/svg"))
    viewer_dir: str = field(default_factory=lambda: os.getenv("VIEWER_DIR", "~/.cache/audio-to-mermaid"))
    viewer_port: int = field(default_factory=lambda: int(os.getenv("VIEWER_PORT", "8765")))
    sample_rate: int = 16000
    chunk_frames: int = 1024
    vad_threshold: float = 0.5
    min_speech_duration: float = 1.0
    max_speech_duration: float = 30.0
    blackhole_device_name: str = "BlackHole"
    mic_device_name: str = "Jabra"

    def validate(self):
        if not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY not set. Copy .env.example to .env and fill it in.")


config = Config()
