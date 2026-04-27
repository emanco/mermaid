import asyncio
import re

import anthropic
from src.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from src.llm.context_manager import ContextManager
from src.utils.config import config
from src.utils.state import state
from src.utils.logger import log


# Auto-fix common Mermaid syntax mistakes the LLM repeatedly makes despite
# explicit prompt rules. Each entry is (pattern, replacement, description).
_MERMAID_FIXUPS: list[tuple[re.Pattern, str, str]] = [
    # Dashed edge with quoted label, malformed dot counts. Valid Mermaid is
    # `A -. "label" .-> B` (or unquoted `A -.label.-> B`). The LLM regularly
    # invents `-.."x"..->`, `-.."x".->`, `-."x"..->`, etc. Match any 1+ dots
    # on either side of a quoted label, normalise to the spaced single-dot form.
    # Also handles -x and -o arrowhead variants.
    (re.compile(r'-\.+("[^"]*")\.+-([->ox])'),
     r'-. \1 .-\2',
     "malformed dashed edge label"),
]


def _normalise_mermaid(source: str) -> str:
    fixed = source
    for pattern, repl, desc in _MERMAID_FIXUPS:
        new, count = pattern.subn(repl, fixed)
        if count:
            log.info(f"Auto-fixed {count}x: {desc}")
            fixed = new
    return fixed


class DiagramGenerator:
    def __init__(self, context_manager: ContextManager):
        self.context = context_manager
        self.client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)
        self._debounce_task: asyncio.Task | None = None
        self._generating = False

    async def on_new_transcript(self):
        # Auto-draw only the first diagram. Once a diagram exists,
        # redraws must be triggered by the Ctrl+Shift+M shortcut.
        if state.get_diagram():
            return
        if self.context.char_count() < config.min_context_chars_for_auto_draw:
            return
        if self._debounce_task and not self._debounce_task.done():
            return
        self._debounce_task = asyncio.create_task(self._debounced_generate())

    async def force_generate(self):
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        await self._generate()

    async def _debounced_generate(self):
        try:
            await asyncio.sleep(config.debounce_seconds)
            await self._generate()
        except asyncio.CancelledError:
            pass

    async def _generate(self):
        if self._generating:
            return
        if not self.context.has_new_content():
            log.debug("No new content, skipping generation")
            return

        self._generating = True
        try:
            transcript = self.context.get_context()
            current = state.get_diagram()

            log.info("Generating diagram update...")
            user_prompt = build_user_prompt(transcript, current)

            response = await self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=8192,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )

            result = response.content[0].text.strip()

            if result == "NO_UPDATE":
                log.info("LLM: no meaningful update needed")
            else:
                # Strip any line that is solely a markdown fence — leading,
                # trailing, or stray mid-output (LLMs sometimes emit them
                # despite instructions, and a single stray ``` breaks the
                # Mermaid parser).
                cleaned_lines = [
                    line for line in result.split("\n")
                    if not line.strip().startswith("```")
                ]
                result = "\n".join(cleaned_lines).strip()
                result = _normalise_mermaid(result)

                state.set_diagram(result)
                log.info(f"Diagram updated ({len(result)} chars)")

            self.context.mark_generated()
        except Exception as e:
            log.error(f"Diagram generation failed: {e}")
        finally:
            self._generating = False
