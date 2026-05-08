import json
import logging
import os

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """Persistent JSON-backed knowledge base for the agent.

    Stores a flat dict of {section_id: content} and renders it as XML for
    inclusion in the system prompt.
    """

    def __init__(self, path: str):
        self.path = path
        self.data = {}
        self._load()

    def _load(self):
        """Load data from the JSON file. On any error, start fresh."""
        if not os.path.exists(self.path):
            self.data = {}
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    self.data = loaded
                else:
                    logger.warning(
                        f"Knowledge base at {self.path} is not a dict; starting fresh."
                    )
                    self.data = {}
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(
                f"Failed to load knowledge base at {self.path}: {e}. Starting fresh."
            )
            self.data = {}

    def _save(self):
        """Persist current data to disk as JSON."""
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def add(self, section_id: str, content: str):
        """Add (or set) an entry, then persist."""
        self.data[section_id] = content
        self._save()

    def edit(self, section_id: str, content: str):
        """Replace an entry, then persist."""
        self.data[section_id] = content
        self._save()

    def delete(self, section_id: str):
        """Remove an entry, then persist. Raises KeyError if missing."""
        if section_id not in self.data:
            raise KeyError(section_id)
        del self.data[section_id]
        self._save()

    def render(self) -> str:
        """Render the knowledge base as an XML string."""
        if not self.data:
            return "<knowledge_base></knowledge_base>"
        lines = ["<knowledge_base>"]
        for section_id, content in self.data.items():
            lines.append(f'<section id="{section_id}">{content}</section>')
        lines.append("</knowledge_base>")
        return "\n".join(lines)
