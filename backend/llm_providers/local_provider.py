"""Local/Ollama provider implementation."""
import json
import logging
import requests
from typing import List, Dict, Any
from ..llm_fallback import LLMProvider, LLMRequest, LLMResponse

logger = logging.getLogger(__name__)

class LocalProvider(LLMProvider):
    def __init__(self, cfg: Dict[str, Any]):
        self.model = cfg.get("model", "llama3.1")
        self.base_url = cfg.get("base_url", "http://localhost:11434")
        self.temperature = cfg.get("temperature", 0.1)
        self.max_tokens = cfg.get("max_tokens", 2000)

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def review(self, request: LLMRequest) -> LLMResponse:
        if not self.is_available():
            raise RuntimeError("Local Ollama server not available")

        prompt = self._build_prompt(request)
        
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": self._system_prompt() + "\n\n" + prompt,
                    "stream": False,
                    "options": {
                        "temperature": self.temperature,
                        "num_predict": self.max_tokens
                    }
                },
                timeout=60
            )
            response.raise_for_status()
            
            result = response.json()
            corrected = json.loads(result.get("response", "{}"))
            
            return LLMResponse(
                corrected_json=corrected.get("corrected", {}),
                confidence=corrected.get("confidence", 0.6),
                changes_made=corrected.get("changes", [])
            )
        except Exception as e:
            logger.error(f"Local LLM review failed: {e}")
            raise

    def _system_prompt(self) -> str:
        return """You are a resume extraction reviewer. Return JSON with:
{
  "corrected": { ... },
  "confidence": 0.0-1.0,
  "changes": ["field: old → new", ...]
}"""

    def _build_prompt(self, req: LLMRequest) -> str:
        import json
        return f"""Resume text:
{req.resume_text[:8000]}

Current extraction (overall score: {req.overall_score}/100):
{json.dumps(req.extracted_json, indent=2)}

Low confidence fields: {', '.join(req.low_confidence_fields)}

Return only the JSON response."""