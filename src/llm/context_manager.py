import threading
from src.utils.config import config
from src.utils.logger import log


class ContextManager:
    def __init__(self):
        self._lines: list[str] = []
        self._lock = threading.Lock()
        self._new_lines_since_last_generate = 0

    def add_line(self, speaker: str, text: str):
        with self._lock:
            self._lines.append(f"{speaker}: {text}")
            self._new_lines_since_last_generate += 1
            self._trim()

    def get_context(self) -> str:
        with self._lock:
            return "\n".join(self._lines)

    def has_new_content(self) -> bool:
        with self._lock:
            return self._new_lines_since_last_generate > 0

    def char_count(self) -> int:
        with self._lock:
            return sum(len(line) for line in self._lines)

    def mark_generated(self):
        with self._lock:
            self._new_lines_since_last_generate = 0

    def get_all_lines(self) -> list[str]:
        with self._lock:
            return list(self._lines)

    def _trim(self):
        # rough estimate: 1 token ~= 4 chars
        max_chars = config.max_context_tokens * 4
        total = sum(len(line) for line in self._lines)
        while total > max_chars and len(self._lines) > 1:
            removed = self._lines.pop(0)
            total -= len(removed)
