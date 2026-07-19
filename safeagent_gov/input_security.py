"""Public PromptShield-Gov API."""

from importlib import import_module

_promptshield = import_module("skills.promptshield-gov.src")
detect_input_risk = _promptshield.detect_input_risk
classify_input_risk = _promptshield.classify_input_risk
cascade_detect = _promptshield.cascade_detect
analyze_sources = _promptshield.analyze_sources
analyze_text_input = _promptshield.analyze_text_input
analyze_input_bundle = _promptshield.analyze_input_bundle
adapt_user_input = _promptshield.adapt_user_input
adapt_web_content = _promptshield.adapt_web_content
adapt_document = _promptshield.adapt_document
adapt_text_source = _promptshield.adapt_text_source
adapt_rag_results = _promptshield.adapt_rag_results
adapt_memory_records = _promptshield.adapt_memory_records

__all__ = [
    "detect_input_risk",
    "classify_input_risk",
    "cascade_detect",
    "analyze_sources",
    "analyze_input_bundle",
    "analyze_text_input",
    "adapt_user_input",
    "adapt_web_content",
    "adapt_document",
    "adapt_text_source",
    "adapt_rag_results",
    "adapt_memory_records",
]
