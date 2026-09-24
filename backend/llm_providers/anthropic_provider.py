"""Anthropic provider implementation."""
import os
import json
import logging
from typing import List, Dict, Any
from ..llm_fallback import LLMProvider, LLMRequest, LLMResponse

logger = logging.getLogger(__name__)

class AnthropicProvider(LLMProvider):
    def __init__(self, cfg: Dict[str, Any]):
        self.model = cfg.get("model", "claude-3-5-haiku-20241022")
        self.temperature = cfg.get("temperature", 0.1)
        self.max_tokens = cfg.get("max_tokens", 2000)
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        self._client = None

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise RuntimeError("ANTHROPIC_API_KEY not set")
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def review(self, request: LLMRequest) -> LLMResponse:
        if not self.is_available():
            raise RuntimeError("Anthropic API key not configured")

        prompt = self._build_prompt(request)
        client = self._get_client()
        
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=self._system_prompt(),
                messages=[{"role": "user", "content": prompt}]
            )
            
            corrected = json.loads(response.content[0].text)
            
            return LLMResponse(
                corrected_json=corrected.get("corrected", {}),
                confidence=corrected.get("confidence", 0.7),
                changes_made=corrected.get("changes", [])
            )
        except Exception as e:
            logger.error(f"Anthropic review failed: {e}")
            raise

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

    def _build_prompt(self, req: LLMRequest) -> str:
        import json
        return f"""Resume text:
{req.resume_text[:8000]}

Current extraction (overall score: {req.overall_score}/100):
{json.dumps(req.extracted_json, indent=2)}

Low confidence fields: {', '.join(req.low_confidence_fields)}

Please review and correct. Return only the JSON response."""