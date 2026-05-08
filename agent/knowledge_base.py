import json
import logging
import os
from html import escape

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """Persistent JSON-backed knowledge base for the agent.

    Stores a flat dict of {section_id: content} and renders it as XML for
    inclusion in the system prompt. Entry values are escaped on render so that
    user/model-supplied text containing ``<``, ``>``, ``&``, or ``"`` cannot
    corrupt the XML structure or be misinterpreted as new tags.
    """

    def __init__(self, path: str):
        self.path = path
        self.data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        """Load data from the JSON file. On any error, start fresh.

        After loading, drop any non-string values defensively — an externally
        edited file with malformed types should not crash rendering.
        """
        if not os.path.exists(self.path):
            self.data = {}
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(
                f"Failed to load knowledge base at {self.path}: {e}. Starting fresh."
            )
            self.data = {}
            return

        if not isinstance(loaded, dict):
            logger.warning(
                f"Knowledge base at {self.path} is not a dict; starting fresh."
            )
            self.data = {}
            return

        cleaned: dict[str, str] = {}
        for k, v in loaded.items():
            if isinstance(k, str) and isinstance(v, str):
                cleaned[k] = v
            else:
                logger.warning(
                    f"Knowledge base entry {k!r} has non-string key or value; dropping."
                )
        self.data = cleaned

    def _save(self) -> None:
        """Persist current data to disk as JSON.

        Writes to a temp file then atomically renames so a crash mid-write
        cannot leave a truncated knowledge_base.json on disk.
        """
        tmp_path = f"{self.path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.path)
        except OSError as e:
            logger.error(f"Failed to persist knowledge base to {self.path}: {e}")
            # Clean up the temp file if it exists
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            raise

    def _validate_section_id(self, section_id) -> str:
        """Validate that section_id is a non-empty string. Raises ValueError otherwise."""
        if not isinstance(section_id, str) or not section_id.strip():
            raise ValueError("section_id must be a non-empty string")
        return section_id.strip()

    def add(self, section_id: str, content: str) -> None:
        """Add (or set) an entry, then persist."""
        section_id = self._validate_section_id(section_id)
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        self.data[section_id] = content
        self._save()

    def edit(self, section_id: str, content: str) -> None:
        """Replace an entry, then persist."""
        section_id = self._validate_section_id(section_id)
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        self.data[section_id] = content
        self._save()

    def delete(self, section_id: str) -> None:
        """Remove an entry, then persist. Raises KeyError if missing."""
        section_id = self._validate_section_id(section_id)
        if section_id not in self.data:
            raise KeyError(section_id)
        del self.data[section_id]
        self._save()

    def render(self) -> str:
        """Render the knowledge base as an XML string.

        Both section IDs and content are HTML-escaped so that text containing
        XML-special characters cannot break the structure or smuggle tags.
        """
        if not self.data:
            return "<knowledge_base></knowledge_base>"
        lines = ["<knowledge_base>"]
        for section_id, content in self.data.items():
            safe_id = escape(section_id, quote=True)
            safe_content = escape(content, quote=False)
            lines.append(f'<section id="{safe_id}">{safe_content}</section>')
        lines.append("</knowledge_base>")
        return "\n".join(lines)
