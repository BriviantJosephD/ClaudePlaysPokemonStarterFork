import base64
import copy
import io
import logging
import os
from datetime import datetime

from config import MAX_TOKENS, MODEL_NAME, TEMPERATURE, USE_NAVIGATOR, SAVE_STATE_INTERVAL, SAVE_STATE_DIR, THOUGHTS_LOG_PATH, THOUGHTS_LOG_TRUNCATE_ON_START, THINKING_ENABLED, THINKING_BUDGET_TOKENS, KNOWLEDGE_BASE_PATH, CRITIC_ENABLED, CRITIC_MODEL, CRITIC_MAX_TOKENS, CRITIC_INTERVAL, OVERLAY_ENABLED, MODEL_PRICING_PER_MTOK

from agent.critic import KnowledgeBaseCritic
from agent.emulator import Emulator
from agent.knowledge_base import KnowledgeBase
from agent.reminders import compute_helpful_reminders
from anthropic import Anthropic

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def get_screenshot_base64(screenshot, upscale=1):
    """Convert PIL image to base64 string."""
    # Resize if needed
    if upscale > 1:
        new_size = (screenshot.width * upscale, screenshot.height * upscale)
        screenshot = screenshot.resize(new_size)

    # Convert to base64
    buffered = io.BytesIO()
    screenshot.save(buffered, format="PNG")
    return base64.standard_b64encode(buffered.getvalue()).decode()


def append_thought(text: str) -> None:
    """Append a model text block to the rolling thoughts log."""
    try:
        with open(THOUGHTS_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat(timespec='seconds')}]\n{text}\n\n")
    except OSError as e:
        logger.error(f"Failed to write thought to {THOUGHTS_LOG_PATH}: {e}")




SYSTEM_PROMPT = """You are playing Pokemon Red. You can see the game screen and control the game by executing emulator commands.

Your goal is to play through Pokemon Red and eventually defeat the Elite Four. Make decisions based on what you see on the screen, what your tools report from RAM, and what is in your long-term knowledge base.

Before each action, explain your reasoning briefly, then use a tool to execute your chosen commands.

# Tool usage

- press_buttons: your default action. Pass an array of buttons in order, e.g. ["a", "a", "down"]. Each press advances the game one input. Prefer short sequences (1-4 buttons) so you can re-evaluate the screen between actions. Use "a" to confirm/talk/select, "b" to cancel/back, and arrows to move or change menu cursor.
- navigate_to (only if available): when you are in the overworld and know the destination tile coordinates, this is far more reliable than chaining presses. Use it instead of guessing long arrow sequences.
- update_knowledge_base: write durable facts here. Use it MORE OFTEN than you think you need to. Small, well-named entries beat one giant note. Good entries: gym leader weaknesses, NPC locations, item shop inventories, completed objectives, current sub-goal. Bad entries: vague feelings, things already in the summary.

# Things you are bad at — be careful

- DO NOT trust pixel-level vision. The screenshot can mislead you on tile boundaries, NPC positions, and menu cursor state. When the RAM state ("State from RAM" block) contradicts the screenshot, TRUST THE RAM. Use RAM-derived position, party stats, and dialog text over visual interpretation.
- You frequently miscount tiles. If you need to move N tiles, prefer navigate_to (when available) over pressing arrow N times.
- You forget to heal. Check party HP before entering caves, gyms, or routes with strong trainers. PokeCenters are free — overuse them.
- You get stuck in menus. If buttons aren't producing visible change after 2-3 tries, you are likely in an unexpected menu state — press "b" repeatedly to back out, then re-evaluate.
- You re-attempt failed strategies. Before retrying something that didn't work, check your knowledge base for prior notes about it.

# Knowledge base discipline

- Update your KB at least once per major event: new town entered, badge earned, item obtained, party change, gym leader defeated.
- After each summarization you may receive a CRITIC REVIEW. Treat its bullets as advisory — apply the ones you agree with, ignore the rest.

# Summarization

The conversation history is summarized periodically to save context. When you see a "CONVERSATION HISTORY SUMMARY" message, that is your only record of recent events — use it for continuity. The knowledge base persists across summarizations and is the right place for facts you want to retain long-term."""

SUMMARY_PROMPT = """I need you to create a detailed summary of our conversation history up to this point. This summary will replace the full conversation history to manage the context window.

Please include:
1. Key game events and milestones you've reached
2. Important decisions you've made
3. Current objectives or goals you're working toward
4. Your current location and Pokémon team status
5. Any strategies or plans you've mentioned

The summary should be comprehensive enough that you can continue gameplay without losing important context about what has happened so far."""


AVAILABLE_TOOLS = [
    {
        "name": "press_buttons",
        "description": "Press a sequence of buttons on the Game Boy.",
        "input_schema": {
            "type": "object",
            "properties": {
                "buttons": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["a", "b", "start", "select", "up", "down", "left", "right"]
                    },
                    "description": "List of buttons to press in sequence. Valid buttons: 'a', 'b', 'start', 'select', 'up', 'down', 'left', 'right'"
                },
                "wait": {
                    "type": "boolean",
                    "description": "Whether to wait for a brief period after pressing each button. Defaults to true."
                }
            },
            "required": ["buttons"],
        },
    }
]

AVAILABLE_TOOLS.append({
    "name": "update_knowledge_base",
    "description": (
        "Add, edit, or delete a section in your long-term knowledge base. "
        "Use this to record durable facts, observations, or strategies you "
        "want to remember across summarizations. For 'add' and 'edit', the "
        "'content' field is REQUIRED. For 'delete', 'content' is ignored."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["add", "edit", "delete"],
                "description": "The operation to perform.",
            },
            "section_id": {
                "type": "string",
                "minLength": 1,
                "description": "Non-empty identifier for the section (e.g. 'brock', 'starter_choice').",
            },
            "content": {
                "type": "string",
                "description": "Content for add/edit. Required for those operations. Ignored for delete.",
            },
        },
        "required": ["operation", "section_id"],
    },
})

if USE_NAVIGATOR:
    AVAILABLE_TOOLS.append({
        "name": "navigate_to",
        "description": "Automatically navigate to a position on the map grid. The screen is divided into a 9x10 grid, with the top-left corner as (0, 0). This tool is only available in the overworld.",
        "input_schema": {
            "type": "object",
            "properties": {
                "row": {
                    "type": "integer",
                    "description": "The row coordinate to navigate to (0-8)."
                },
                "col": {
                    "type": "integer",
                    "description": "The column coordinate to navigate to (0-9)."
                }
            },
            "required": ["row", "col"],
        },
    })


class SimpleAgent:
    def __init__(self, rom_path, headless=True, sound=False, max_history=60, load_state=None):
        """Initialize the simple agent.

        Args:
            rom_path: Path to the ROM file
            headless: Whether to run without display
            sound: Whether to enable sound
            max_history: Maximum number of messages in history before summarization
        """
        self.emulator = Emulator(rom_path, headless, sound)
        self.emulator.initialize()  # Initialize the emulator
        os.makedirs(SAVE_STATE_DIR, exist_ok=True)
        self.knowledge_base = KnowledgeBase(KNOWLEDGE_BASE_PATH)
        self.client = Anthropic()
        # Share the Anthropic client between main agent and critic to avoid
        # spinning up a second HTTP connection pool.
        self.critic = KnowledgeBaseCritic(
            model=CRITIC_MODEL,
            max_tokens=CRITIC_MAX_TOKENS,
            enabled=CRITIC_ENABLED,
            client=self.client,
        )
        self.running = True
        # Seeded below, after load_state and other setup, with the first
        # observation (screenshot + overlay + RAM state). Initialized empty
        # here so the helper can run with a valid object on self.
        self.message_history = []
        self.max_history = max_history
        # Total step counter persists across multiple run() calls so the
        # save-state interval triggers correctly even when the caller invokes
        # run() in small batches (e.g. main.py default --steps 10).
        self._total_steps = 0
        # Number of summarization events that have fired this session. Used
        # to gate the critic on CRITIC_INTERVAL — only every Nth summary
        # triggers a critic review.
        self._summary_count = 0

        # Ensure the directory containing THOUGHTS_LOG_PATH exists so
        # append_thought() can write even when the user points the log at a
        # subdirectory like "logs/thoughts.log".
        thoughts_parent = os.path.dirname(THOUGHTS_LOG_PATH)
        if thoughts_parent:
            try:
                os.makedirs(thoughts_parent, exist_ok=True)
            except OSError as e:
                logger.error(f"[Thoughts] Failed to create dir {thoughts_parent}: {e}")

        # Roll the rolling thoughts log so each session starts clean and the
        # file does not grow unbounded across multi-day streams. Archive the
        # prior file as <path>.prev rather than deleting it — preserves the
        # last session for forensic review and is atomic on POSIX (the OBS
        # panel sees the new empty file the next tick instead of mid-write).
        if THOUGHTS_LOG_TRUNCATE_ON_START:
            try:
                if os.path.exists(THOUGHTS_LOG_PATH):
                    archive_path = THOUGHTS_LOG_PATH + ".prev"
                    os.replace(THOUGHTS_LOG_PATH, archive_path)
                    logger.info(
                        f"[Thoughts] Archived prior {THOUGHTS_LOG_PATH} → {archive_path}"
                    )
            except OSError as e:
                logger.error(f"[Thoughts] Failed to archive {THOUGHTS_LOG_PATH}: {e}")

        if load_state:
            logger.info(f"Loading saved state from {load_state}")
            self.emulator.load_state(load_state)

        # Seed the first user turn with a real observation so the model's
        # first response is grounded in screenshot + RAM state instead of
        # acting blind. Done AFTER load_state so the observation reflects the
        # loaded state, not the pre-load state. If observation capture fails
        # for any reason we fall back to the bare framing string rather than
        # crashing the agent before it ever ran.
        try:
            self.message_history = [self._build_initial_observation_message()]
        except Exception as e:  # noqa: BLE001 — defensive, must not abort init
            logger.exception(f"[Init] Failed to build first observation: {e}")
            self.message_history = [
                {"role": "user", "content": "You may now begin playing."}
            ]

        # One-shot startup log so a viewer of the run log can see exactly
        # which model + features the agent is configured with.
        logger.info(
            "[Config] model=%s temperature=%s max_tokens=%s thinking=%s "
            "thinking_budget=%s critic_enabled=%s critic_model=%s "
            "critic_interval=%s overlay=%s save_interval=%s max_history=%s",
            MODEL_NAME, TEMPERATURE, MAX_TOKENS,
            THINKING_ENABLED, THINKING_BUDGET_TOKENS,
            CRITIC_ENABLED, CRITIC_MODEL, CRITIC_INTERVAL,
            OVERLAY_ENABLED, SAVE_STATE_INTERVAL, max_history,
        )
        self._log_cost_estimate()

    def _build_initial_observation_message(self):
        """Build the first user message with a real observation.

        Captures screenshot + walkability overlay + RAM state and packages
        them as a plain user message (NOT a tool_result, since there's no
        prior tool_use to attach to). The model's very first turn then has
        the same grounding signals as every subsequent turn — without this
        the first decision would be made blind.
        """
        screenshot = self.emulator.get_screenshot()
        screenshot_b64 = get_screenshot_base64(screenshot, upscale=2)

        overlay_img = (
            self.emulator.get_collision_overlay_image() if OVERLAY_ENABLED else None
        )
        overlay_b64 = (
            get_screenshot_base64(overlay_img, upscale=1) if overlay_img is not None else None
        )

        memory_info = self.emulator.get_state_from_memory()
        logger.info("[Memory State at session start]")
        logger.info(memory_info)

        content = [
            {
                "type": "text",
                "text": (
                    "Initial observation. You may now begin playing. "
                    "Your first action should be informed by the screenshot, "
                    "overlay, and memory state below — do not act blind."
                ),
            },
            {"type": "text", "text": "\nCurrent screen:"},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": screenshot_b64,
                },
            },
        ]

        if overlay_b64 is not None:
            content.append({
                "type": "text",
                "text": (
                    "\nWalkability overlay (red=blocked, green=walkable, "
                    "yellow box=NPC/sprite, blue box=you):"
                ),
            })
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": overlay_b64,
                },
            })

        content.append({
            "type": "text",
            "text": f"\nGame state information from memory:\n{memory_info}",
        })

        return {"role": "user", "content": content}

    def _log_cost_estimate(self):
        """Print an order-of-magnitude $/hour estimate for the configured run.

        Uses the per-turn token shape from the README and looks up pricing
        in MODEL_PRICING_PER_MTOK by prefix-match (so dated snapshots like
        "claude-sonnet-4-5-20250929" still resolve). Cache-hit pricing is
        not modeled — expect realized cost to be 30-60% lower with a stable
        system prompt. Logs a warning and skips silently if pricing is not
        configured for the chosen model.
        """
        def _lookup(model_id):
            for prefix, prices in MODEL_PRICING_PER_MTOK.items():
                if model_id.startswith(prefix):
                    return prices
            return None

        main = _lookup(MODEL_NAME)
        if main is None:
            logger.warning(
                "[Cost] No pricing configured for model %r; "
                "edit MODEL_PRICING_PER_MTOK in config.py to enable estimates.",
                MODEL_NAME,
            )
            return

        in_per_mtok, out_per_mtok = main
        # Per-turn shape from the README's worked example.
        input_tok = 7000
        output_tok = 1000
        thinking_tok = THINKING_BUDGET_TOKENS if THINKING_ENABLED else 0
        # Thinking is billed at the output rate per Anthropic's pricing model.
        per_turn_cost = (
            input_tok * in_per_mtok + (output_tok + thinking_tok) * out_per_mtok
        ) / 1_000_000

        # Critic contribution: amortized across summarizations. The critic
        # fires every CRITIC_INTERVAL summaries, and each summary fires every
        # ~30 turns (max_history default). So the per-turn share is divided
        # by (30 * CRITIC_INTERVAL). Skip when the critic is disabled or the
        # critic model has no pricing entry.
        critic = _lookup(CRITIC_MODEL) if CRITIC_ENABLED and CRITIC_INTERVAL > 0 else None
        if critic:
            critic_in_mtok, critic_out_mtok = critic
            # Rough critic shape: small input (KB + summary), short output.
            critic_input_tok = 2000
            critic_output_tok = CRITIC_MAX_TOKENS
            critic_call_cost = (
                critic_input_tok * critic_in_mtok + critic_output_tok * critic_out_mtok
            ) / 1_000_000
            turns_per_summary = 30 * CRITIC_INTERVAL
            per_turn_cost += critic_call_cost / turns_per_summary

        # Throughput: ~8-15s/turn with thinking + tool use + emulator stepping.
        turns_per_hour_low, turns_per_hour_high = 250, 450
        cost_low = per_turn_cost * turns_per_hour_low
        cost_high = per_turn_cost * turns_per_hour_high

        logger.info(
            "[Cost] Per-turn ≈ %.4f USD (incl. amortized critic); "
            "expected %d-%d turns/hr → ~$%.0f-$%.0f/hr at list pricing, no caching. "
            "Realized cost is typically 30-60%% lower with prompt caching.",
            per_turn_cost,
            turns_per_hour_low, turns_per_hour_high,
            cost_low, cost_high,
        )

    def _build_emulator_tool_result(self, tool_use_id, action_summary, screenshot_intro):
        """Build a tool_result for press_buttons or navigate_to.

        Captures a fresh screenshot (raw and walkability-overlay variants),
        the parsed RAM state, and the ASCII collision map for logging. The
        overlay image is included when available; if rendering fails the
        result still contains the plain screenshot.

        Args:
            tool_use_id: ID of the originating tool_use block.
            action_summary: First text block describing what happened, e.g.
                "Pressed buttons: a, b" or "Navigation result: ...".
            screenshot_intro: Short label preceding the plain screenshot.
        """
        # Plain screenshot, upscaled 2x for legibility.
        screenshot = self.emulator.get_screenshot()
        screenshot_b64 = get_screenshot_base64(screenshot, upscale=2)

        # Walkability image overlay. None on failure — degrade gracefully.
        # The overlay is already rendered at 2x resolution (320x288) inside
        # get_collision_overlay_image, so we pass upscale=1 here on purpose;
        # do NOT change to upscale=2 or the payload doubles in dimensions.
        overlay_img = (
            self.emulator.get_collision_overlay_image() if OVERLAY_ENABLED else None
        )
        overlay_b64 = (
            get_screenshot_base64(overlay_img, upscale=1) if overlay_img is not None else None
        )

        # RAM-derived state (canonical source of truth) and ASCII collision
        # map (for logs only — the image overlay is the model-visible version).
        memory_info = self.emulator.get_state_from_memory()
        logger.info("[Memory State after action]")
        logger.info(memory_info)
        collision_map = self.emulator.get_collision_map()
        if collision_map:
            logger.info(f"[Collision Map after action]\n{collision_map}")

        content = [
            {"type": "text", "text": action_summary},
            {"type": "text", "text": f"\n{screenshot_intro}"},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": screenshot_b64,
                },
            },
        ]

        if overlay_b64 is not None:
            content.append({
                "type": "text",
                "text": (
                    "\nWalkability overlay (red=blocked, green=walkable, "
                    "yellow box=NPC/sprite, blue box=you):"
                ),
            })
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": overlay_b64,
                },
            })

        content.append({
            "type": "text",
            "text": f"\nGame state information from memory after your action:\n{memory_info}",
        })

        # Situational reminders (low HP, in-battle, dialog active, narrow
        # passage, navigation failure). compute_helpful_reminders never raises;
        # an empty list means we add nothing — no token waste.
        reminders = compute_helpful_reminders(memory_info, collision_map, action_summary)
        if reminders:
            content.append({
                "type": "text",
                "text": "\nHelpful reminders:\n" + "\n".join(f"- {r}" for r in reminders),
            })

        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": content,
        }

    def process_tool_call(self, tool_call):
        """Process a single tool call."""
        tool_name = tool_call.name
        tool_input = tool_call.input
        logger.info(f"Processing tool call: {tool_name}")

        if tool_name == "press_buttons":
            buttons = tool_input["buttons"]
            wait = tool_input.get("wait", True)
            logger.info(f"[Buttons] Pressing: {buttons} (wait={wait})")

            self.emulator.press_buttons(buttons, wait)

            return self._build_emulator_tool_result(
                tool_use_id=tool_call.id,
                action_summary=f"Pressed buttons: {', '.join(buttons)}",
                screenshot_intro="Here is a screenshot of the screen after your button presses:",
            )
        elif tool_name == "navigate_to":
            row = tool_input["row"]
            col = tool_input["col"]
            logger.info(f"[Navigation] Navigating to: ({row}, {col})")

            status, path = self.emulator.find_path(row, col)
            if path:
                for direction in path:
                    self.emulator.press_buttons([direction], True)
                result = f"Navigation successful: followed path with {len(path)} steps"
            else:
                result = f"Navigation failed: {status}"

            return self._build_emulator_tool_result(
                tool_use_id=tool_call.id,
                action_summary=f"Navigation result: {result}",
                screenshot_intro="Here is a screenshot of the screen after navigation:",
            )
        elif tool_name == "update_knowledge_base":
            operation = tool_input.get("operation")
            section_id = tool_input.get("section_id")
            content = tool_input.get("content")
            logger.info(
                f"[KnowledgeBase] {operation} section {section_id!r}"
            )

            # Validate inputs before touching the KB.
            if operation not in ("add", "edit", "delete"):
                message = (
                    f"Error: unknown knowledge base operation {operation!r}. "
                    "Must be one of: add, edit, delete."
                )
            elif not isinstance(section_id, str) or not section_id.strip():
                message = "Error: section_id must be a non-empty string."
            elif operation in ("add", "edit") and not isinstance(content, str):
                message = (
                    f"Error: '{operation}' requires a 'content' string. "
                    "Pass the section text in the 'content' field."
                )
            else:
                try:
                    if operation == "add":
                        self.knowledge_base.add(section_id, content)
                        message = f"Knowledge base updated: added section '{section_id}'"
                    elif operation == "edit":
                        self.knowledge_base.edit(section_id, content)
                        message = f"Knowledge base updated: edited section '{section_id}'"
                    else:  # delete
                        self.knowledge_base.delete(section_id)
                        message = f"Knowledge base updated: deleted section '{section_id}'"
                except KeyError:
                    message = (
                        f"Error: section '{section_id}' not found in knowledge base."
                    )
                except (ValueError, OSError) as e:
                    message = f"Error updating knowledge base: {e}"

            return {
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": [
                    {"type": "text", "text": message},
                ],
            }
        else:
            logger.error(f"Unknown tool called: {tool_name}")
            return {
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": [
                    {"type": "text", "text": f"Error: Unknown tool '{tool_name}'"}
                ],
            }

    def run(self, num_steps=1):
        """Main agent loop.

        Args:
            num_steps: Number of steps to run for
        """
        logger.info(f"Starting agent loop for {num_steps} steps")

        steps_completed = 0
        while self.running and steps_completed < num_steps:
            try:
                messages = copy.deepcopy(self.message_history)

                if len(messages) >= 3:
                    if messages[-1]["role"] == "user" and isinstance(messages[-1]["content"], list) and messages[-1]["content"]:
                        messages[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}
                    
                    if len(messages) >= 5 and messages[-3]["role"] == "user" and isinstance(messages[-3]["content"], list) and messages[-3]["content"]:
                        messages[-3]["content"][-1]["cache_control"] = {"type": "ephemeral"}


                # Build optional thinking kwarg
                extra_kwargs = {}
                if THINKING_ENABLED:
                    extra_kwargs["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": THINKING_BUDGET_TOKENS,
                    }

                system_with_kb = SYSTEM_PROMPT + "\n\n" + self.knowledge_base.render()

                # Get model response
                response = self.client.messages.create(
                    model=MODEL_NAME,
                    max_tokens=MAX_TOKENS,
                    system=system_with_kb,
                    messages=messages,
                    tools=AVAILABLE_TOOLS,
                    temperature=TEMPERATURE,
                    **extra_kwargs,
                )

                logger.info(f"Response usage: {response.usage}")

                # Extract tool calls
                tool_calls = [
                    block for block in response.content if block.type == "tool_use"
                ]

                # Display the model's reasoning
                for block in response.content:
                    if block.type == "text":
                        logger.info(f"[Text] {block.text}")
                        append_thought(block.text)
                    elif block.type == "tool_use":
                        logger.info(f"[Tool] Using tool: {block.name}")
                    elif block.type == "thinking":
                        logger.info(f"[Thinking] {block.thinking}")

                # Process tool calls
                if tool_calls:
                    # Add assistant message to history.
                    # Preserve thinking AND redacted_thinking blocks in their
                    # original order. The Anthropic API rejects subsequent
                    # tool_result turns if these blocks are missing or reordered
                    # when extended thinking is enabled.
                    assistant_content = []
                    for block in response.content:
                        if block.type == "thinking":
                            assistant_content.append({
                                "type": "thinking",
                                "thinking": block.thinking,
                                "signature": block.signature,
                            })
                        elif block.type == "redacted_thinking":
                            # Safety-redacted thinking: preserve the opaque
                            # data payload so the API can verify continuity.
                            assistant_content.append({
                                "type": "redacted_thinking",
                                "data": block.data,
                            })
                        elif block.type == "text":
                            assistant_content.append({"type": "text", "text": block.text})
                        elif block.type == "tool_use":
                            # Use model_dump() for forward compatibility with
                            # newer Pydantic / Anthropic SDK versions.
                            dumped = block.model_dump() if hasattr(block, "model_dump") else dict(block)
                            assistant_content.append(dumped)

                    self.message_history.append(
                        {"role": "assistant", "content": assistant_content}
                    )
                    
                    # Process tool calls and create tool results
                    tool_results = []
                    for tool_call in tool_calls:
                        tool_result = self.process_tool_call(tool_call)
                        tool_results.append(tool_result)
                    
                    # Add tool results to message history
                    self.message_history.append(
                        {"role": "user", "content": tool_results}
                    )

                    # Check if we need to summarize the history
                    if len(self.message_history) >= self.max_history:
                        self.summarize_history()

                steps_completed += 1
                self._total_steps += 1
                logger.info(f"Completed step {steps_completed}/{num_steps} (total {self._total_steps})")

                # Use the persistent total counter so the save interval still
                # triggers when run() is called in small batches.
                if self._total_steps % SAVE_STATE_INTERVAL == 0:
                    save_path = os.path.join(
                        SAVE_STATE_DIR, f"autosave_step_{self._total_steps}.state"
                    )
                    try:
                        self.emulator.save_state(save_path)
                        logger.info(f"[Save] Wrote state to {save_path}")
                    except OSError as e:
                        logger.error(f"[Save] Failed to write state to {save_path}: {e}")

            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt, stopping")
                self.running = False
            except Exception as e:
                logger.error(f"Error in agent loop: {e}")
                raise e

        if not self.running:
            self.emulator.stop()

        return steps_completed

    def summarize_history(self):
        """Generate a summary of the conversation history and replace the history with just the summary."""
        logger.info(f"[Agent] Generating conversation summary...")
        
        # Get a new screenshot for the summary
        screenshot = self.emulator.get_screenshot()
        screenshot_b64 = get_screenshot_base64(screenshot, upscale=2)
        
        # Create messages for the summarization request - pass the entire conversation history
        messages = copy.deepcopy(self.message_history) 


        if len(messages) >= 3:
            if messages[-1]["role"] == "user" and isinstance(messages[-1]["content"], list) and messages[-1]["content"]:
                messages[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}
            
            if len(messages) >= 5 and messages[-3]["role"] == "user" and isinstance(messages[-3]["content"], list) and messages[-3]["content"]:
                messages[-3]["content"][-1]["cache_control"] = {"type": "ephemeral"}

        messages += [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": SUMMARY_PROMPT,
                    }
                ],
            }
        ]
        
        # Build optional thinking kwarg
        extra_kwargs = {}
        if THINKING_ENABLED:
            extra_kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": THINKING_BUDGET_TOKENS,
            }

        system_with_kb = SYSTEM_PROMPT + "\n\n" + self.knowledge_base.render()

        # Get summary from Claude
        response = self.client.messages.create(
            model=MODEL_NAME,
            max_tokens=MAX_TOKENS,
            system=system_with_kb,
            messages=messages,
            temperature=TEMPERATURE,
            **extra_kwargs,
        )
        
        # Extract the summary text
        summary_text = " ".join([block.text for block in response.content if block.type == "text"])

        logger.info(f"[Agent] Game Progress Summary:")
        logger.info(f"{summary_text}")

        # Run the knowledge-base critic. Returns None if disabled, KB is fine,
        # or the API call fails. Any feedback gets appended to the next turn's
        # user message so the main agent self-corrects its KB hygiene.
        # Gated by CRITIC_INTERVAL: the critic runs only on every Nth
        # summarization event (1 = every summary; 2 = every other; etc.).
        # Skipped intervals are logged so the user can verify the cadence.
        self._summary_count += 1
        if CRITIC_INTERVAL <= 0 or self._summary_count % CRITIC_INTERVAL != 0:
            logger.info(
                "[Critic] Skipped (summary %d, interval %d)",
                self._summary_count, CRITIC_INTERVAL,
            )
            critique = None
        else:
            critique = self.critic.review(
                knowledge_base_xml=self.knowledge_base.render(),
                summary_text=summary_text,
            )

        # Build the rebuilt history's content blocks.
        new_content = [
            {
                "type": "text",
                "text": f"CONVERSATION HISTORY SUMMARY (representing {self.max_history} previous messages): {summary_text}"
            },
            {
                "type": "text",
                "text": "\n\nCurrent game screenshot for reference:"
            },
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": screenshot_b64,
                },
            },
            {
                "type": "text",
                "text": "You were just asked to summarize your playthrough so far, which is the summary you see above. You may now continue playing by selecting your next action."
            },
        ]

        if critique:
            new_content.append({
                "type": "text",
                "text": (
                    "\n\nCRITIC REVIEW OF YOUR KNOWLEDGE BASE "
                    "(advisory — review these suggestions and use update_knowledge_base "
                    "to act on the ones you agree with):\n"
                    f"{critique}"
                ),
            })

        # Replace message history with just the summary (+ optional critique)
        self.message_history = [{"role": "user", "content": new_content}]

        logger.info(f"[Agent] Message history condensed into summary.")
        
    def stop(self):
        """Stop the agent.

        Writes a final save state if any progress was made, then shuts down
        the emulator. A failure to save is logged but does not block shutdown.
        """
        self.running = False
        if self._total_steps > 0:
            final_path = os.path.join(
                SAVE_STATE_DIR, f"autosave_step_{self._total_steps}_final.state"
            )
            try:
                self.emulator.save_state(final_path)
                logger.info(f"[Save] Wrote final state to {final_path}")
            except OSError as e:
                logger.error(f"[Save] Failed to write final state to {final_path}: {e}")
        self.emulator.stop()


if __name__ == "__main__":
    # Get the ROM path relative to this file
    current_dir = os.path.dirname(os.path.abspath(__file__))
    rom_path = os.path.join(os.path.dirname(current_dir), "pokemon.gb")

    # Create and run agent
    agent = SimpleAgent(rom_path)

    try:
        steps_completed = agent.run(num_steps=10)
        logger.info(f"Agent completed {steps_completed} steps")
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, stopping")
    finally:
        agent.stop()