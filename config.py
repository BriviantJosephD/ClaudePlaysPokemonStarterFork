# Configuration for the application
MODEL_NAME = "claude-3-7-sonnet-20250219"
TEMPERATURE = 1.0
MAX_TOKENS = 4000

USE_NAVIGATOR = False

SAVE_STATE_INTERVAL = 50   # Save every N agent steps
SAVE_STATE_DIR = "saves"

THOUGHTS_LOG_PATH = "thoughts.log"
THOUGHTS_HTML_PORT = 7861

THINKING_ENABLED = True
THINKING_BUDGET_TOKENS = 2000

KNOWLEDGE_BASE_PATH = "knowledge_base.json"
