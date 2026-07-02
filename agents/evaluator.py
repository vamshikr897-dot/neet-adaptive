import logging

from agents.ollama_client import AgentGenerationError, call_structured
from models.agent_io import EvaluatorLLMResult, EvaluatorResult

logger = logging.getLogger("neet_adaptive.evaluator")

_KEYWORD_FALLBACK_MAP = [
    (["sign", "calculation", "unit", "arithmetic", "algebra"], "calculation_error"),
    (["exception", "forgot", "edge_case", "special_case"], "exception_not_known"),
]


def _fallback_failure_mode(misconception_tag: str) -> str:
    tag_lower = misconception_tag.lower()
    for keywords, mode in _KEYWORD_FALLBACK_MAP:
        if any(k in tag_lower for k in keywords):
            return mode
    return "conceptual_gap"


def _build_system_prompt() -> str:
    return """You are diagnosing a NEET student's wrong answer on a multiple-choice question.
You will be given the question, the option the student selected, and the tagged rationale for
why that option is wrong. Classify the failure into exactly one of:
- conceptual_gap: the student fundamentally misunderstands the underlying concept
- calculation_error: the student understood the concept but made an arithmetic/algebraic mistake
- exception_not_known: the student didn't know a specific exception/edge-case to the general rule

Write a short (1-2 sentence) reasoning explaining the diagnosis, grounded in the provided rationale."""


def _build_user_prompt(question: dict, selected_option: str) -> str:
    rationale = next(
        (r for r in question["distractor_rationale"] if r["option_key"] == selected_option), None
    )
    rationale_text = (
        f"misconception_tag={rationale['misconception_tag']}, explanation={rationale['explanation']}"
        if rationale
        else "no rationale found for this option"
    )
    return (
        f"Question: {question['stem']}\n"
        f"Options: {question['options']}\n"
        f"Correct option: {question['correct_option']}\n"
        f"Student selected: {selected_option}\n"
        f"Tagged rationale for the student's selection: {rationale_text}"
    )


def evaluate_answer(question: dict, selected_option: str | None) -> EvaluatorResult:
    correct = selected_option is not None and selected_option == question["correct_option"]

    if selected_option is None:
        return EvaluatorResult(
            correct=False, failure_mode="conceptual_gap", reasoning="No answer was submitted in time.",
            rationale_tag=None,
        )

    # Every option (including the correct one) carries a tagged rationale explaining why it's
    # right/wrong - looked up once here so both the correct and incorrect paths can attach it.
    rationale = next(
        (r for r in question["distractor_rationale"] if r["option_key"] == selected_option), None
    )
    rationale_tag = rationale["misconception_tag"] if rationale else None
    rationale_explanation = rationale["explanation"] if rationale else None

    if correct:
        return EvaluatorResult(
            correct=True, failure_mode="none", reasoning="",
            rationale_tag=rationale_tag, rationale_explanation=rationale_explanation,
        )

    try:
        llm_result = call_structured(
            _build_system_prompt(), _build_user_prompt(question, selected_option), EvaluatorLLMResult
        )
        return EvaluatorResult(
            correct=False, failure_mode=llm_result.failure_mode, reasoning=llm_result.reasoning,
            rationale_tag=rationale_tag, rationale_explanation=rationale_explanation,
        )
    except AgentGenerationError:
        logger.warning("Evaluator LLM call failed twice, using deterministic fallback")
        fallback_mode = _fallback_failure_mode(rationale_tag or "unknown")
        fallback_reasoning = rationale_explanation or "Incorrect option selected."
        return EvaluatorResult(
            correct=False, failure_mode=fallback_mode, reasoning=fallback_reasoning,
            rationale_tag=rationale_tag, rationale_explanation=rationale_explanation,
        )
