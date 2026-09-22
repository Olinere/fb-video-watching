"""Runtime-only persistence policy for private viewing sessions."""

from dataclasses import dataclass
import re


@dataclass(slots=True)
class RuntimePersistencePolicy:
    """Central policy object; modules do not inspect GUI flags directly."""

    enabled: bool = False

    def is_enabled(self) -> bool:
        return self.enabled

    def allow_history_write(self) -> bool:
        return not self.enabled

    def allow_resume_write(self) -> bool:
        return not self.enabled

    def allow_content_state_write(self) -> bool:
        return not self.enabled

    def allow_explicit_user_settings_write(self) -> bool:
        return True

    def allow_queue_persist(self) -> bool:
        return not self.enabled

    def redact_diagnostics(self) -> bool:
        return self.enabled

    def redact(self, value: str) -> str:
        """Remove query/fragment data from diagnostic text in private mode."""
        if not self.enabled or not value:
            return value
        return re.sub(r"https?://[^\s]+", "<private-url>", str(value))

