import base64
import copy
import io
import logging
import os
from datetime import datetime

from config import MAX_TOKENS, MODEL_NAME, TEMPERATURE, USE_NAVIGATOR, SAVE_STATE_INTERVAL, SAVE_STATE_DIR, THOUGHTS_LOG_PATH, THINKING_ENABLED, THINKING_BUDGET_TOKENS, KNOWLEDGE_BASE_PATH, CRITIC_ENABLED, CRITIC_MODEL, CRITIC_MAX_TOKENS

from agent.critic import KnowledgeBaseCritic
from agent.emulator import Emulator
from agent.knowledge_base import KnowledgeBase
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
        self.message_history = [{"role": "user", "content": "You may now begin playing."}]
        self.max_history = max_history
        # Total step counter persists across multiple run() calls so the
        # save-state interval triggers correctly even when the caller invokes
        # run() in small batches (e.g. main.py default --steps 10).
        self._total_steps = 0
        if load_state:
            logger.info(f"Loading saved state from {load_state}")
            self.emulator.load_state(load_state)

    def process_tool_call(self, tool_call):
        """Process a single tool call."""
        tool_name = tool_call.name
        tool_input = tool_call.input
        logger.info(f"Processing tool call: {tool_name}")

        if tool_name == "press_buttons":
            buttons = tool_input["buttons"]
            wait = tool_input.get("wait", True)
            logger.info(f"[Buttons] Pressing: {buttons} (wait={wait})")
            
            result = self.emulator.press_buttons(buttons, wait)
            
            # Get a fresh screenshot after executing the buttons
            screenshot = self.emulator.get_screenshot()
            screenshot_b64 = get_screenshot_base64(screenshot, upscale=2)
            
            # Get game state from memory after the action
            memory_info = self.emulator.get_state_from_memory()
            
            # Log the memory state after the tool call
            logger.info(f"[Memory State after action]")
            logger.info(memory_info)
            
            collision_map = self.emulator.get_collision_map()
            if collision_map:
                logger.info(f"[Collision Map after action]\n{collision_map}")
            
            # Return tool result as a dictionary
            return {
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": [
                    {"type": "text", "text": f"Pressed buttons: {', '.join(buttons)}"},
                    {"type": "text", "text": "\nHere is a screenshot of the screen after your button presses:"},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": screenshot_b64,
                        },
                    },
                    {"type": "text", "text": f"\nGame state information from memory after your action:\n{memory_info}"},
                ],
            }
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
            
            # Get a fresh screenshot after executing the navigation
            screenshot = self.emulator.get_screenshot()
            screenshot_b64 = get_screenshot_base64(screenshot, upscale=2)
            
            # Get game state from memory after the action
            memory_info = self.emulator.get_state_from_memory()
            
            # Log the memory state after the tool call
            logger.info(f"[Memory State after action]")
            logger.info(memory_info)
            
            collision_map = self.emulator.get_collision_map()
            if collision_map:
                logger.info(f"[Collision Map after action]\n{collision_map}")
            
            # Return tool result as a dictionary
            return {
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": [
                    {"type": "text", "text": f"Navigation result: {result}"},
                    {"type": "text", "text": "\nHere is a screenshot of the screen after navigation:"},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": screenshot_b64,
                        },
                    },
                    {"type": "text", "text": f"\nGame state information from memory after your action:\n{memory_info}"},
                ],
            }
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