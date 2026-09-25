"""Provider-agnostic LLM fallback interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Any
from pathlib import Path
import yaml
import logging

logger = logging.getLogger(__name__)

@dataclass
class LLMRequest:
    resume_text: str
    extracted_json: Dict[str, Any]
    low_confidence_fields: List[str]
    overall_score: int

@dataclass
class LLMResponse:
    corrected_json: Dict[str, Any]
    confidence: float
    changes_made: List[str]

class LLMProvider(ABC):
    @abstractmethod
    def review(self, request: LLMRequest) -> LLMResponse:
        pass

    @abstractmethod
    def is_available(self) -> bool:
        pass


class DisabledProvider(LLMProvider):
    """Default provider: LLM tier explicitly disabled (resumes hold PII).

    Never calls any model; the runner treats this as unavailable and
    routes to human review.
    """

    def __init__(self, cfg=None):
        self.cfg = cfg or {}

    def is_available(self) -> bool:
        return False

    def review(self, request: LLMRequest) -> LLMResponse:
        raise RuntimeError("LLM tier is disabled (provider: disabled)")

_provider_cache = None

def get_provider(config: Dict[str, Any] = None) -> LLMProvider:
    """Factory - returns configured provider."""
    global _provider_cache
    if _provider_cache is not None:
        return _provider_cache
    
    if config is None:
        cfg_path = Path(__file__).parents[1] / "config" / "routing.yaml"
        with open(cfg_path) as f:
            config = yaml.safe_load(f)
    
    llm_cfg = config.get("llm", {})
    provider_name = llm_cfg.get("provider", "disabled")

    if provider_name == "disabled":
        _provider_cache = DisabledProvider(llm_cfg)
        return _provider_cache

    if provider_name == "openai":
        from .llm_providers.openai_provider import OpenAIProvider
        _provider_cache = OpenAIProvider(llm_cfg)
    elif provider_name == "deepseek":
        from .llm_providers.deepseek_provider import DeepSeekProvider
        _provider_cache = DeepSeekProvider(llm_cfg)
    elif provider_name == "anthropic":
        from .llm_providers.anthropic_provider import AnthropicProvider
        _provider_cache = AnthropicProvider(llm_cfg)
    elif provider_name == "local":
        from .llm_providers.local_provider import LocalProvider
        _provider_cache = LocalProvider(llm_cfg)
    else:
        raise ValueError(f"Unknown LLM provider: {provider_name}")
    
    return _provider_cache

def _identify_low_confidence_fields(extracted_json: Dict[str, Any]) -> List[str]:
    """Return list of field paths with confidence < 70%."""
    fields = []
    timeline = extracted_json.get("timeline", []) if isinstance(extracted_json, dict) else []
    for event in timeline:
        if not isinstance(event, dict):
            continue
        conf = event.get("confidence", 1)
        if conf < 0.7:
            event_id = event.get("id", "unknown")
            for field in ["title", "org", "start", "end"]:
                if not event.get("source", {}).get(field):
                    fields.append(f"{event_id}.{field}")
    return fields

def _validate_llm_output(corrected: Dict[str, Any], resume_text: str) -> bool:
    """Validate LLM output against resume text - dates/orgs must appear."""
    if not isinstance(corrected, dict):
        return False
    
    timeline = corrected.get("timeline", [])
    if not isinstance(timeline, list):
        return False
    
    text_lower = resume_text.lower()
    for event in timeline:
        if not isinstance(event, dict):
            continue
        
        # Check org appears in resume
        org = event.get("org", "")
        if org and org.lower() not in text_lower:
            return False
        
        # Check dates are plausible (year in resume)
        start = event.get("start", "")
        if start and isinstance(start, str):
            year = start[:4]
            if year.isdigit() and year not in text_lower:
                return False
        
        end = event.get("end", "")
        if end and isinstance(end, str) and end != "present":
            year = end[:4]
            if year.isdigit() and year not in text_lower:
                return False
    
    return True

def _merge_corrections(original: Dict[str, Any], corrections: Dict[str, Any],
                       allowed_fields: List[str] = None):
    """Merge LLM corrections into the original DTO.

    Only fields listed in ``allowed_fields`` (the low-confidence field paths
    ``<event_id>.<field>``) may be overwritten. Every applied change is tagged
    with provenance ``"llm"`` on the event and recorded (with the original
    value) in the returned applied-changes list.

    Returns ``(merged, applied)`` where ``applied`` is a list of
    ``{"event_id", "field", "old", "new", "provenance": "llm"}`` dicts.
    """
    import copy
    result = copy.deepcopy(original)
    applied = []

    if not isinstance(corrections, dict):
        return result, applied

    orig_timeline = result.get("timeline", [])
    corr_timeline = corrections.get("timeline", [])

    if not isinstance(orig_timeline, list) or not isinstance(corr_timeline, list):
        return result, applied

    allowed = set(allowed_fields or [])
    # Build lookup for corrections by event id
    corr_by_id = {e.get("id"): e for e in corr_timeline if isinstance(e, dict) and e.get("id")}

    for i, orig_event in enumerate(orig_timeline):
        if not isinstance(orig_event, dict):
            continue
        event_id = orig_event.get("id")
        if not event_id or event_id not in corr_by_id:
            continue

        corr_event = corr_by_id[event_id]
        for field in ["title", "org", "start", "end"]:
            path = f"{event_id}.{field}"
            if allowed and path not in allowed:
                continue
            if field in corr_event and corr_event[field] is not None:
                old = orig_event.get(field)
                new = corr_event[field]
                if old != new:
                    orig_timeline[i][field] = new
                    prov = orig_timeline[i].setdefault("provenance", {})
                    prov[field] = "llm"
                    applied.append({"event_id": event_id, "field": field,
                                    "old": old, "new": new, "provenance": "llm"})

    return result, applied