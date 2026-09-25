"""DeepSeek provider implementation."""
import os
import json
import logging
from typing import List, Dict, Any
from ..llm_fallback import LLMProvider, LLMRequest, LLMResponse

from pathlib import Path

logger = logging.getLogger(__name__)


def _strip_markdown_and_extract_json(text: str) -> str:
    """Clean markdown code blocks and extract JSON object substring."""
    s = text.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()

    first_brace = s.find("{")
    last_brace = s.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        s = s[first_brace:last_brace + 1]
    return s


class DeepSeekProvider(LLMProvider):
    def __init__(self, cfg: Dict[str, Any]):
        self.model = cfg.get("model", "deepseek-chat")
        self.temperature = cfg.get("temperature", 0.1)
        self.max_tokens = cfg.get("max_tokens", 4096)
        self.base_url = cfg.get("base_url", "https://api.deepseek.com")
        self.config_api_key = cfg.get("api_key")
        self._client = None

    def _get_api_key(self) -> str:
        key = os.getenv("DEEPSEEK_API_KEY") or self.config_api_key
        if not key:
            env_file = Path(__file__).resolve().parents[2] / ".env"
            if env_file.exists():
                for line in env_file.read_text().splitlines():
                    line = line.strip()
                    if line.startswith("DEEPSEEK_API_KEY="):
                        key = line.split("=", 1)[1].strip().strip('"\'')
                        break
        return key or ""

    def is_available(self) -> bool:
        return bool(self._get_api_key())

    def _get_client(self):
        api_key = self._get_api_key()
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY not set")
        try:
            import openai
            if self._client is None:
                self._client = openai.OpenAI(api_key=api_key, base_url=self.base_url)
            return self._client
        except ImportError:
            return None

    def _call_api(self, prompt: str, system_prompt: str, api_key: str) -> str:
        client = self._get_client()
        if client is not None:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"}
            )
            return response.choices[0].message.content

        import urllib.request
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"}
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            return resp_data["choices"][0]["message"]["content"]

    def review(self, request: LLMRequest) -> LLMResponse:
        if not self.is_available():
            raise RuntimeError("DeepSeek API key not configured")

        api_key = self._get_api_key()
        prompt = self._build_prompt(request)

        raw_content = ""
        try:
            raw_content = self._call_api(prompt, self._system_prompt(), api_key)
            cleaned = _strip_markdown_and_extract_json(raw_content)
            corrected = json.loads(cleaned)
        except Exception as e:
            logger.error("DeepSeek raw unparsed response (attempt 1, %d chars):\n%s", len(raw_content), raw_content)
            logger.warning("DeepSeek review attempt 1 failed (%s); retrying with strict JSON prompt...", e)
            try:
                raw_content = self._call_api(prompt, self._strict_system_prompt(), api_key)
                cleaned = _strip_markdown_and_extract_json(raw_content)
                corrected = json.loads(cleaned)
            except Exception as e_retry:
                logger.error("DeepSeek raw unparsed response on retry (attempt 2, %d chars):\n%s", len(raw_content), raw_content)
                logger.error("DeepSeek review retry failed: %s", e_retry)
                raise RuntimeError(f"DeepSeek JSON parse failed after retry: {e_retry}") from e_retry

        return LLMResponse(
            corrected_json=corrected.get("corrected", {}),
            confidence=corrected.get("confidence", 0.7),
            changes_made=corrected.get("changes", [])
        )

    def _system_prompt(self) -> str:
        return """You are a resume extraction reviewer. You receive:
1. Original resume text
2. Current extraction JSON with confidence issues
3. List of low-confidence fields

Return JSON with:
{
  "corrected": { ... full corrected extraction ... },
  "confidence": 0.0-1.0,
  "changes": ["field: old → new", ...]
}

Only correct fields that are clearly wrong. Preserve correct extractions."""

    def _strict_system_prompt(self) -> str:
        return """CRITICAL: Return ONLY valid, parseable raw JSON matching the schema below.
DO NOT output markdown code fences like ```json or ```.
DO NOT include any introductory or concluding text, comments, or notes.
Your entire output must start with '{' and end with '}'.

Schema:
{
  "corrected": { ... full corrected extraction ... },
  "confidence": 0.0-1.0,
  "changes": ["field: old → new", ...]
}"""

    def _build_prompt(self, req: LLMRequest) -> str:
        return f"""Resume text:
{req.resume_text[:8000]}

Current extraction (overall score: {req.overall_score}/100):
{json.dumps(req.extracted_json, indent=2)}

Low confidence fields: {', '.join(req.low_confidence_fields)}

Please review and correct. Return only the JSON response."""
