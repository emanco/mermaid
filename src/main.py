import asyncio
import signal
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from src.audio.devices import get_mic_device, get_blackhole_device, list_devices
from src.audio.capture import AudioStream
from src.audio.vad import VoiceActivityDetector
from src.transcription.whisper_engine import transcribe, get_model
from src.llm.context_manager import ContextManager
from src.llm.diagram_generator import DiagramGenerator
from src.render.mermaid_viewer import MermaidViewer
from src.shortcuts.hotkeys import start_hotkeys, stop_hotkeys
from src.utils.config import config
from src.utils.state import state
from src.utils.logger import log


class App:
    def __init__(self):
        self.context = ContextManager()
        self.generator = DiagramGenerator(self.context)
        self.viewer = MermaidViewer()
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.mic_stream: AudioStream | None = None
        self.system_stream: AudioStream | None = None
        self.mic_vad = VoiceActivityDetector()
        self.system_vad = VoiceActivityDetector()
        self._last_pasted_diagram = ""

    async def start(self):
        config.validate()

        log.info("=" * 50)
        log.info("Audio-to-Mermaid Diagram Tool")
        log.info("=" * 50)
        list_devices()

        # Load whisper model upfront
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self.executor, get_model)

        # Setup audio devices
        mic_dev = get_mic_device()
        mic_idx = next(
            i for i, d in enumerate(__import__("sounddevice").query_devices())
            if d["name"] == mic_dev["name"] and d["max_input_channels"] > 0
        )

        try:
            bh_dev = get_blackhole_device()
            bh_idx = next(
                i for i, d in enumerate(__import__("sounddevice").query_devices())
                if d["name"] == bh_dev["name"] and d["max_input_channels"] > 0
            )
            self.system_stream = AudioStream(bh_idx, "INTERVIEWER")
        except RuntimeError:
            log.warning("Running without system audio capture (mic only mode)")

        self.mic_stream = AudioStream(mic_idx, "ME")

        # Start the local viewer (Kroki SVG + tiny HTTP server)
        try:
            await self.viewer.start()
        except Exception as e:
            log.warning(f"Viewer failed to start ({e}). Diagrams will print to terminal only.")

        # Start audio streams
        self.mic_stream.start()
        if self.system_stream:
            self.system_stream.start()

        # Start hotkeys
        start_hotkeys()

        log.info("")
        log.info("Ready! Listening for audio.")
        log.info("Diagram updates hands-free as the conversation evolves.")
        log.info("Press Ctrl+Shift+M to force a redraw immediately.")
        log.info("Press Ctrl+C to quit.")
        log.info("")

        # Main loop
        try:
            await self._run_loop()
        finally:
            await self.shutdown()

    async def _run_loop(self):
        loop = asyncio.get_event_loop()

        while not state.is_shutting_down:
            # Process mic audio
            if self.mic_stream:
                chunks = self.mic_stream.get_chunks()
                for chunk in chunks:
                    segments = self.mic_vad.process(chunk)
                    for seg in segments:
                        text = await loop.run_in_executor(self.executor, transcribe, seg)
                        if text:
                            self.context.add_line("ME", text)
                            state.add_transcript("ME", text)
                            log.info(f"[ME] {text}")
                            await self.generator.on_new_transcript()

            # Process system audio
            if self.system_stream:
                chunks = self.system_stream.get_chunks()
                for chunk in chunks:
                    segments = self.system_vad.process(chunk)
                    for seg in segments:
                        text = await loop.run_in_executor(self.executor, transcribe, seg)
                        if text:
                            self.context.add_line("INTERVIEWER", text)
                            state.add_transcript("INTERVIEWER", text)
                            log.info(f"[INTERVIEWER] {text}")
                            await self.generator.on_new_transcript()

            # Check for generate request
            if state.consume_regenerate():
                await self.generator.force_generate()

            # Render diagram if updated
            current = state.get_diagram()
            if current and current != self._last_pasted_diagram:
                self._last_pasted_diagram = current
                log.info("--- MERMAID DIAGRAM ---")
                log.info(current)
                log.info("--- END DIAGRAM ---")
                try:
                    await self.viewer.render(current)
                except Exception as e:
                    log.error(f"Render failed: {e}")

            await asyncio.sleep(0.1)  # 100ms polling

    async def shutdown(self):
        log.info("Shutting down...")
        state.is_shutting_down = True

        if self.mic_stream:
            self.mic_stream.stop()
        if self.system_stream:
            self.system_stream.stop()

        stop_hotkeys()
        self.viewer.stop()
        self.executor.shutdown(wait=False)

        # Save transcript and diagram
        output_dir = Path(__file__).resolve().parents[1] / "transcripts"
        output_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        transcript = state.get_transcript()
        if transcript:
            transcript_file = output_dir / f"transcript_{ts}.txt"
            transcript_file.write_text("\n".join(transcript))
            log.info(f"Transcript saved: {transcript_file}")

        diagram = state.get_diagram()
        if diagram:
            diagram_file = output_dir / f"diagram_{ts}.mmd"
            diagram_file.write_text(diagram)
            log.info(f"Diagram saved: {diagram_file}")

        log.info("Goodbye!")


def main():
    app = App()

    def handle_signal(sig, frame):
        state.is_shutting_down = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        asyncio.run(app.start())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
