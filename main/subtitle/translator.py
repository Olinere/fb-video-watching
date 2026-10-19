"""
Pluggable AI Subtitle Translator module.
Provides an abstract base interface and an OpenAI-compatible completion implementation
(/v1/chat/completions) supporting OpenAI, Google Gemini, Groq, DeepSeek, Ollama, etc.
"""

from abc import ABC, abstractmethod
import json
import logging
from typing import Dict, Any, List, Optional
import urllib.request
import urllib.error

from .cue_parser import SubtitleCue

logger = logging.getLogger(__name__)


class BaseSubtitleTranslator(ABC):
    """Abstract base class for subtitle translators."""

    @abstractmethod
    def translate_cues(
        self,
        cues: List[SubtitleCue],
        source_lang: str = "auto",
        target_lang: str = "vi",
    ) -> List[SubtitleCue]:
        """
        Translate a list of SubtitleCue objects into target_lang.
        Must preserve timestamps and cue indices.
        """
        pass


class OpenAICompatibleTranslator(BaseSubtitleTranslator):
    """
    OpenAI-compatible chat completion translator (/v1/chat/completions).
    Works with OpenAI (gpt-4o-mini), Gemini (OpenAI endpoint), Groq, DeepSeek, Ollama local.
    """

    def __init__(
        self,
        endpoint: str = "https://api.openai.com/v1",
        api_key: str = "",
        model: str = "gpt-4o-mini",
        timeout_sec: int = 30,
        batch_size: int = 50,
    ):
        self.endpoint = endpoint.rstrip("/")
        if not self.endpoint.endswith("/chat/completions"):
            if not self.endpoint.endswith("/v1"):
                self.endpoint = f"{self.endpoint}/v1/chat/completions"
            else:
                self.endpoint = f"{self.endpoint}/chat/completions"
        self.api_key = api_key.strip()
        self.model = model.strip() or "gpt-4o-mini"
        self.timeout_sec = timeout_sec
        self.batch_size = max(1, min(100, batch_size))

    def _translate_batch(
        self,
        batch: List[SubtitleCue],
        source_lang: str,
        target_lang: str,
    ) -> Dict[int, str]:
        """Translate a batch of cues and return mapping {index: translated_text}."""
        if not batch:
            return {}

        prompt_lines = [f"[{cue.index}] {cue.text}" for cue in batch]
        prompt_content = "\n".join(prompt_lines)

        system_msg = (
            f"You are a subtitle translator. Translate the following numbered subtitle lines into {target_lang}. "
            "Maintain the exact format '[index] translated text'. "
            "Keep translations natural, culturally appropriate, and concise for video reading speed. "
            "Do not output any introductory or concluding text, only the translated lines."
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt_content},
            ],
            "temperature": 0.3,
        }

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "FB-Video-Watching-AI-Subtitle",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.endpoint, data=data, headers=headers, method="POST")

        translated_map: Dict[int, str] = {}
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            choices = result.get("choices", [])
            if not choices:
                return {}

            msg_content = choices[0].get("message", {}).get("content", "")
            for line in msg_content.strip().split("\n"):
                line = line.strip()
                if line.startswith("[") and "]" in line:
                    bracket_end = line.index("]")
                    idx_str = line[1:bracket_end].strip()
                    if idx_str.isdigit():
                        idx = int(idx_str)
                        text = line[bracket_end + 1 :].strip()
                        translated_map[idx] = text

        except Exception as e:
            logger.warning(f"[OpenAICompatibleTranslator] Batch translation failed: {e}")

        return translated_map

    def translate_cues(
        self,
        cues: List[SubtitleCue],
        source_lang: str = "auto",
        target_lang: str = "vi",
    ) -> List[SubtitleCue]:
        """Translate all cues in batches. Preserves cue timing and falls back to original on error."""
        if not cues:
            return []

        out_cues: List[SubtitleCue] = []
        for i in range(0, len(cues), self.batch_size):
            batch = cues[i : i + self.batch_size]
            translated_map = self._translate_batch(batch, source_lang, target_lang)

            for cue in batch:
                new_text = translated_map.get(cue.index, cue.text)
                out_cues.append(SubtitleCue(
                    index=cue.index,
                    start=cue.start,
                    end=cue.end,
                    text=new_text,
                    settings=cue.settings,
                ))

        return out_cues
