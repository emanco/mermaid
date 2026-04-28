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
        # Hands-free: schedule a debounced regen on every new transcript line.
        # The debounce coalesces rapid lines into one call, the char-delta gate
        # in _generate skips when too little has changed, and a Haiku
        # "should we update?" gate skips when the delta is non-architectural.
        # First-draw still requires the minimum-context threshold to avoid
        # drawing from a 3-word fragment.
        if not state.get_diagram() and self.context.char_count() < config.min_context_chars_for_auto_draw:
            return
        if self._debounce_task and not self._debounce_task.done():
            return
        self._debounce_task = asyncio.create_task(self._debounced_generate())

    async def force_generate(self):
        # Ctrl+Shift+M: emergency override — bypass both the char-delta and
        # Haiku gates, always run a full Sonnet regen.
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        await self._generate(force=True)

    async def _debounced_generate(self):
        try:
            await asyncio.sleep(config.debounce_seconds)
            await self._generate(force=False)
        except asyncio.CancelledError:
            pass

    async def _should_update(self, current_diagram: str, delta: str) -> bool:
        """Cheap Haiku call: does this transcript delta merit a full regen?"""
        prompt = (
            "You decide whether a Mermaid system-design diagram should be regenerated "
            "based on a new chunk of interview transcript.\n\n"
            "Reply on ONE line in EXACTLY this form: 'YES: <reason>' or 'NO: <reason>'.\n\n"
            "Reply YES if the new transcript adds architectural information worth reflecting "
            "(new component, requirement, constraint, scale number, trade-off, edge case, "
            "data flow, correction, or interviewer pushback that changes a decision).\n\n"
            "Reply NO for small talk, clarifications of already-captured info, the interviewer "
            "pressing on existing decisions without new info, generic thinking aloud, or filler.\n\n"
            f"CURRENT DIAGRAM:\n{current_diagram}\n\n"
            f"NEW TRANSCRIPT:\n{delta}"
        )
        try:
            response = await self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=80,
                messages=[{"role": "user", "content": prompt}],
            )
            answer = response.content[0].text.strip()
            decision = answer.upper().startswith("YES")
            log.info(f"Haiku gate: {answer[:140]}")
            return decision
        except Exception as e:
            log.warning(f"Haiku gate failed ({e}); defaulting to update")
            return True  # fail open — better to redraw than miss an update

    async def _generate(self, force: bool = False):
        if self._generating:
            return
        if not self.context.has_new_content():
            log.debug("No new content, skipping generation")
            return

        self._generating = True
        try:
            transcript = self.context.get_context()
            current = state.get_diagram()

            # Smart gates (skipped for force=True from Ctrl+Shift+M):
            # 1) Char-delta gate — don't even consider a regen for tiny deltas;
            #    let them accumulate. Don't mark_generated, so the delta keeps growing.
            # 2) Haiku gate — ask a cheap model whether the delta adds architectural info.
            #    If NO, mark_generated (consume the delta) and return.
            if current and not force:
                delta_chars = self.context.new_chars_since_generated()
                if delta_chars < config.min_delta_chars_for_update:
                    log.debug(f"Skip: only {delta_chars} new chars since last update")
                    return
                delta = self.context.get_delta()
                if not await self._should_update(current, delta):
                    self.context.mark_generated()
                    return

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
