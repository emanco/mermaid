import threading
from dataclasses import dataclass, field


@dataclass
class AppState:
    diagram_generation_enabled: bool = False
    force_regenerate: bool = False
    current_diagram: str = ""
    is_shutting_down: bool = False
    transcript_lines: list = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add_transcript(self, speaker: str, text: str):
        with self._lock:
            self.transcript_lines.append(f"{speaker}: {text}")

    def get_transcript(self) -> list[str]:
        with self._lock:
            return list(self.transcript_lines)

    def set_diagram(self, diagram: str):
        with self._lock:
            self.current_diagram = diagram

    def get_diagram(self) -> str:
        with self._lock:
            return self.current_diagram

    def toggle_generation(self) -> bool:
        with self._lock:
            self.diagram_generation_enabled = not self.diagram_generation_enabled
            return self.diagram_generation_enabled

    def request_regenerate(self):
        with self._lock:
            self.force_regenerate = True

    def consume_regenerate(self) -> bool:
        with self._lock:
            val = self.force_regenerate
            self.force_regenerate = False
            return val


state = AppState()
