import logging
from datetime import datetime, timezone

import config
from agents.generator import _TYPE_CYCLE
from agents.ollama_client import AgentGenerationError, call_structured
from agents.time_model import expected_time_seconds
from models.agent_io import ConceptSpec, GapAnalyserLLMResult
from models.report import (
    BloomDokBreakdown,
    ConceptVerdict,
    ErrorAnalysis,
    GapReport,
    LevelBreakdownEntry,
    NeetScore,
    PriorityConcept,
    QuestionHistoryPoint,
    QuestionTypeBreakdownEntry,
    RecoveryProgression,
    StrengthConcept,
    TimeByTypeEntry,
    TimeEfficiency,
)
from models.session_state import DifficultyHistoryEntry, FailureModeTally, SessionState

logger = logging.getLogger("neet_adaptive.gap_analyser")

_FAILURE_MODES = ("conceptual_gap", "calculation_error", "exception_not_known")


def _compute_mastery_pct(history: list[DifficultyHistoryEntry], concept: str) -> float | None:
    entries = [e for e in history if e.concept == concept]
    if not entries:
        return None
    total_difficulty = sum(e.difficulty for e in entries)
    if total_difficulty == 0:
        return None
    correct_difficulty = sum(e.difficulty for e in entries if e.correct)
    return 100.0 * correct_difficulty / total_difficulty


def _compute_verdict(tally: FailureModeTally | None, mastery_pct: float | None) -> tuple[str, str]:
    """Returns (verdict, dominant_failure_mode) from mastery_pct, or not_assessed if no attempts."""
    if tally is None or tally.attempt_count == 0 or mastery_pct is None:
        return "not_assessed", "none"

    if mastery_pct >= config.MASTERY_STRONG_THRESHOLD:
        verdict = "strong"
    elif mastery_pct < config.MASTERY_WEAK_THRESHOLD:
        verdict = "weak"
    else:
        verdict = "needs_improvement"

    if verdict == "strong":
        dominant = "none"
    else:
        counts = {mode: getattr(tally, mode) for mode in _FAILURE_MODES}
        dominant = max(counts, key=lambda m: counts[m]) if any(counts.values()) else "none"

    return verdict, dominant


def _compute_neet_score(history: list[DifficultyHistoryEntry]) -> NeetScore:
    attempted = [e for e in history if e.selected_option is not None]
    correct_count = sum(1 for e in attempted if e.correct)
    incorrect_count = len(attempted) - correct_count
    raw_score = config.NEET_CORRECT_MARKS * correct_count + config.NEET_INCORRECT_MARKS * incorrect_count
    max_score = config.NEET_CORRECT_MARKS * len(attempted)
    score_percentage = (100.0 * raw_score / max_score) if attempted else None

    return NeetScore(
        questions_attempted=len(attempted),
        questions_unattempted=len(history) - len(attempted),
        correct_count=correct_count,
        incorrect_attempted_count=incorrect_count,
        raw_score=raw_score,
        max_score_from_attempted=max_score,
        score_percentage=score_percentage,
        marks_lost_to_negative_marking=incorrect_count,
    )


def _level_breakdown(history: list[DifficultyHistoryEntry], level_attr: str) -> list[LevelBreakdownEntry]:
    groups: dict[int, list[DifficultyHistoryEntry]] = {}
    for e in history:
        if e.selected_option is None:  # skipped/timed-out - excluded, matches _compute_neet_score()
            continue
        level = getattr(e, level_attr)
        if level == 0:  # legacy/unbackfilled - excluded rather than shown as a fake "Level 0"
            continue
        groups.setdefault(level, []).append(e)

    entries = []
    for level in sorted(groups):
        items = groups[level]
        correct = sum(1 for i in items if i.correct)
        entries.append(
            LevelBreakdownEntry(
                level=level, attempted=len(items), correct=correct, accuracy_pct=100.0 * correct / len(items)
            )
        )
    return entries


def _compute_bloom_dok_breakdown(history: list[DifficultyHistoryEntry]) -> BloomDokBreakdown:
    return BloomDokBreakdown(
        bloom=_level_breakdown(history, "bloom_level"),
        dok=_level_breakdown(history, "dok_level"),
    )


def _compute_question_type_breakdown(history: list[DifficultyHistoryEntry]) -> list[QuestionTypeBreakdownEntry]:
    groups: dict[str, list[DifficultyHistoryEntry]] = {}
    for e in history:
        if e.selected_option is None:  # skipped/timed-out - excluded, matches _level_breakdown()
            continue
        groups.setdefault(e.question_type, []).append(e)

    entries = []
    for qtype in _TYPE_CYCLE:  # canonical generation order, not alphabetical
        items = groups.get(qtype)
        if not items:
            continue
        correct = sum(1 for i in items if i.correct)
        entries.append(
            QuestionTypeBreakdownEntry(
                question_type=qtype, attempted=len(items), correct=correct, accuracy_pct=100.0 * correct / len(items)
            )
        )
    return entries


def _compute_error_analysis(failure_mode_tally: dict[str, FailureModeTally]) -> ErrorAnalysis:
    conceptual = sum(t.conceptual_gap for t in failure_mode_tally.values())
    calculation = sum(t.calculation_error for t in failure_mode_tally.values())
    exception = sum(t.exception_not_known for t in failure_mode_tally.values())
    total = conceptual + calculation + exception

    def pct(count: int) -> float | None:
        return (100.0 * count / total) if total > 0 else None

    return ErrorAnalysis(
        conceptual_gap_count=conceptual,
        calculation_error_count=calculation,
        exception_not_known_count=exception,
        total_incorrect_attempted=total,
        conceptual_gap_pct=pct(conceptual),
        calculation_error_pct=pct(calculation),
        exception_not_known_pct=pct(exception),
    )


def _dominant_error_type(error_analysis: ErrorAnalysis) -> str:
    if error_analysis.total_incorrect_attempted == 0:
        return "none"
    counts = {
        "conceptual_gap": error_analysis.conceptual_gap_count,
        "calculation_error": error_analysis.calculation_error_count,
        "exception_not_known": error_analysis.exception_not_known_count,
    }
    return max(counts, key=lambda m: counts[m])


def _compute_time_efficiency(history: list[DifficultyHistoryEntry]) -> TimeEfficiency:
    attempted = [e for e in history if e.selected_option is not None]
    if not attempted:
        return TimeEfficiency(
            avg_actual_seconds=None,
            avg_expected_seconds=None,
            efficiency_ratio=None,
            hesitation_index=None,
            faster_bucket_accuracy_pct=None,
            slower_bucket_accuracy_pct=None,
            faster_bucket_count=0,
            slower_bucket_count=0,
            tradeoff_tag="insufficient_data",
        )

    expected_times = [expected_time_seconds(e.question_type, e.difficulty) for e in attempted]
    ratios = [e.time_taken_seconds / t for e, t in zip(attempted, expected_times)]
    capped_ratios = [min(r, config.TIME_RATIO_OUTLIER_CAP) for r in ratios]

    faster = [e for e, r in zip(attempted, ratios) if r < 1]
    slower = [e for e, r in zip(attempted, ratios) if r >= 1]

    hesitation_count = sum(
        1 for e, r in zip(attempted, ratios) if e.correct and r > config.HESITATION_TIME_RATIO_THRESHOLD
    )
    rushed_guess_count = sum(
        1 for e, r in zip(attempted, ratios) if not e.correct and r < config.GUESS_TIME_RATIO_THRESHOLD
    )

    def bucket_accuracy(bucket: list[DifficultyHistoryEntry]) -> float | None:
        return (100.0 * sum(1 for e in bucket if e.correct) / len(bucket)) if bucket else None

    faster_acc = bucket_accuracy(faster)
    slower_acc = bucket_accuracy(slower)

    if faster_acc is None or slower_acc is None:
        tag = "insufficient_data"
    elif slower_acc - faster_acc >= config.SPEED_ACCURACY_GAP_THRESHOLD_PCT:
        tag = "rushing_costs_accuracy"
    elif faster_acc - slower_acc >= config.SPEED_ACCURACY_GAP_THRESHOLD_PCT:
        tag = "overthinking_without_gain"
    else:
        tag = "well_balanced"

    return TimeEfficiency(
        avg_actual_seconds=sum(e.time_taken_seconds for e in attempted) / len(attempted),
        avg_expected_seconds=sum(expected_times) / len(expected_times),
        efficiency_ratio=sum(capped_ratios) / len(capped_ratios),
        hesitation_index=100.0 * hesitation_count / len(attempted),
        rushed_guess_count=rushed_guess_count,
        faster_bucket_accuracy_pct=faster_acc,
        slower_bucket_accuracy_pct=slower_acc,
        faster_bucket_count=len(faster),
        slower_bucket_count=len(slower),
        tradeoff_tag=tag,
    )


def _compute_recovery_progression(history: list[DifficultyHistoryEntry]) -> RecoveryProgression:
    ordered = sorted(history, key=lambda e: e.question_index)

    total_after_wrong = 0
    correct_after_wrong = 0
    for i in range(len(ordered) - 1):
        if not ordered[i].correct:  # "wrong" includes unattempted - bouncing back from any non-success
            total_after_wrong += 1
            if ordered[i + 1].correct:
                correct_after_wrong += 1
    recovery_rate = (100.0 * correct_after_wrong / total_after_wrong) if total_after_wrong > 0 else None

    if len(ordered) < config.PROGRESSION_MIN_QUESTIONS:
        return RecoveryProgression(
            recovery_rate=recovery_rate,
            total_after_wrong=total_after_wrong,
            correct_after_wrong=correct_after_wrong,
            progression_available=False,
            first_half_accuracy_pct=None,
            second_half_accuracy_pct=None,
            first_half_avg_difficulty=None,
            second_half_avg_difficulty=None,
        )

    mid = len(ordered) // 2  # second half absorbs the remainder on odd-length sessions
    first_half, second_half = ordered[:mid], ordered[mid:]

    def accuracy(bucket: list[DifficultyHistoryEntry]) -> float:
        return 100.0 * sum(1 for e in bucket if e.correct) / len(bucket)

    def avg_difficulty(bucket: list[DifficultyHistoryEntry]) -> float:
        return sum(e.difficulty for e in bucket) / len(bucket)

    return RecoveryProgression(
        recovery_rate=recovery_rate,
        total_after_wrong=total_after_wrong,
        correct_after_wrong=correct_after_wrong,
        progression_available=True,
        first_half_accuracy_pct=accuracy(first_half),
        second_half_accuracy_pct=accuracy(second_half),
        first_half_avg_difficulty=avg_difficulty(first_half),
        second_half_avg_difficulty=avg_difficulty(second_half),
    )


def _compute_priority_concepts(
    verdicts: list[ConceptVerdict], failure_mode_tally: dict[str, FailureModeTally]
) -> list[PriorityConcept]:
    priority = []
    for v in verdicts:
        if v.verdict not in ("weak", "needs_improvement") or v.pyq_weight < config.PRIORITY_CONCEPT_PYQ_WEIGHT_MIN:
            continue
        tally = failure_mode_tally.get(v.concept)
        priority.append(
            PriorityConcept(
                concept=v.concept, verdict=v.verdict, pyq_weight=v.pyq_weight, mastery_pct=v.mastery_pct,
                conceptual_gap=tally.conceptual_gap if tally else 0,
                calculation_error=tally.calculation_error if tally else 0,
                exception_not_known=tally.exception_not_known if tally else 0,
            )
        )
    priority.sort(key=lambda p: p.pyq_weight, reverse=True)
    return priority


def _compute_strength_concepts(verdicts: list[ConceptVerdict]) -> list[StrengthConcept]:
    strengths = [
        StrengthConcept(concept=v.concept, pyq_weight=v.pyq_weight, mastery_pct=v.mastery_pct)
        for v in verdicts
        if v.verdict == "strong"
    ]
    strengths.sort(key=lambda s: s.pyq_weight, reverse=True)
    return strengths


def _collect_rationale_notes(history: list[DifficultyHistoryEntry], concept: str, want_correct: bool) -> list[str]:
    """Rationale explanations (not just tags - a correct answer's tag is always the generic
    string "correct", so the explanation prose is what actually describes the skill shown)."""
    return [
        e.rationale_explanation
        for e in history
        if e.concept == concept and e.correct == want_correct and e.rationale_explanation
    ]


def _compute_time_by_question_type(history: list[DifficultyHistoryEntry]) -> list[TimeByTypeEntry]:
    attempted = [e for e in history if e.selected_option is not None]
    groups: dict[str, list[DifficultyHistoryEntry]] = {}
    for e in attempted:
        groups.setdefault(e.question_type, []).append(e)

    entries = []
    for qtype in _TYPE_CYCLE:
        items = groups.get(qtype)
        if not items:
            continue
        expected_times = [expected_time_seconds(qtype, e.difficulty) for e in items]
        entries.append(
            TimeByTypeEntry(
                question_type=qtype,
                avg_actual_seconds=sum(e.time_taken_seconds for e in items) / len(items),
                avg_expected_seconds=sum(expected_times) / len(expected_times),
                count=len(items),
            )
        )
    return entries


def _build_question_history(history: list[DifficultyHistoryEntry]) -> list[QuestionHistoryPoint]:
    ordered = sorted(history, key=lambda e: e.question_index)
    return [
        QuestionHistoryPoint(
            question_index=e.question_index,
            time_taken_seconds=e.time_taken_seconds,
            correct=e.correct,
            difficulty=e.difficulty,
            concept=e.concept,
            attempted=e.selected_option is not None,
        )
        for e in ordered
    ]


def _build_system_prompt() -> str:
    return (
        "You are writing a personalised performance report for a NEET student. "
        "The verdict for each concept (strong / weak / needs_improvement / not_assessed), the dominant "
        "failure mode, and every other computed statistic (NEET score, mastery percentages, error "
        "breakdown, time efficiency, recovery rate, etc.) have already been finalized from the data — "
        "you must NOT change, recompute, or contradict any of them. Your only job is to write:\n"
        "1. For EVERY concept, one concept_narrations entry with a short (1-2 sentence) reasoning "
        "explaining the verdict in plain language a student can act on.\n"
        "2. For concepts marked [PRIORITY] below, also fill that SAME entry's misconception_note: read "
        "its wrong-answer explanations and name the SPECIFIC recurring mistake, not a restatement of "
        "the verdict. If the explanations don't share a clear thread, describe the most instructive "
        "single mistake instead of forcing a pattern.\n"
        "3. For concepts marked [STRENGTH] below, also fill that SAME entry's expertise_note: read its "
        "correct-answer explanations and name the SPECIFIC skill/concept demonstrably mastered.\n"
        "4. Leave misconception_note and expertise_note as empty strings \"\" for every other concept.\n"
        "5. A 2-4 sentence overall summary highlighting the student's top strength, biggest gap, and "
        "the single most important next step.\n"
        "6. A next_steps list of 2-3 short, concrete, prioritized actions before the next attempt "
        "(e.g. 'Redo numerical problems on Concept X' not 'study more').\n"
        "Each concept_narrations entry MUST be a JSON object with exactly these 4 keys: concept, "
        "reasoning, misconception_note, expertise_note - for example: "
        '{"concept": "Circular Motion", "reasoning": "...", "misconception_note": "...", "expertise_note": ""}\n'
        "Be specific, warm, and actionable. Avoid generic filler."
    )


def _build_user_prompt(
    verdicts: list[ConceptVerdict],
    neet_score: NeetScore,
    error_analysis: ErrorAnalysis,
    time_efficiency: TimeEfficiency,
    recovery_progression: RecoveryProgression,
    priority_concepts: list[PriorityConcept],
    strength_concepts: list[StrengthConcept],
    history: list[DifficultyHistoryEntry],
) -> str:
    priority_names = {p.concept for p in priority_concepts}
    strength_names = {s.concept for s in strength_concepts}

    lines = ["Concept performance data (verdicts are final — only write the reasoning/notes):"]
    for v in verdicts:
        mastery_str = f"{v.mastery_pct:.0f}% mastery" if v.mastery_pct is not None else "not assessed"
        line = (
            f"- {v.concept}: verdict={v.verdict}, dominant_failure={v.dominant_failure_mode}, "
            f"{v.correct}/{v.questions_asked} correct ({mastery_str})"
        )
        if v.concept in priority_names:
            notes = _collect_rationale_notes(history, v.concept, want_correct=False)
            notes_str = " | ".join(notes) if notes else "no wrong-answer explanations available"
            line += f" [PRIORITY - wrong-answer explanations: {notes_str}]"
        if v.concept in strength_names:
            notes = _collect_rationale_notes(history, v.concept, want_correct=True)
            notes_str = " | ".join(notes) if notes else "no correct-answer explanations available"
            line += f" [STRENGTH - correct-answer explanations: {notes_str}]"
        lines.append(line)

    lines.append("\nSession-wide stats (final, do not alter):")
    score_line = f"NEET score: {neet_score.raw_score}/{neet_score.max_score_from_attempted}"
    if neet_score.score_percentage is not None:
        score_line += f" ({neet_score.score_percentage:.0f}%)"
    lines.append(score_line)

    if error_analysis.total_incorrect_attempted > 0:
        lines.append(f"Most common error type: {_dominant_error_type(error_analysis)}")
    if time_efficiency.efficiency_ratio is not None:
        lines.append(
            f"Time efficiency: {time_efficiency.efficiency_ratio:.2f}x expected time "
            f"(tradeoff: {time_efficiency.tradeoff_tag})"
        )
    if recovery_progression.recovery_rate is not None:
        lines.append(f"Recovery rate after mistakes: {recovery_progression.recovery_rate:.0f}%")

    lines.append(
        "\nReturn concept_narrations (one object per concept above, in the same order, each with "
        "concept/reasoning/misconception_note/expertise_note keys), a summary, and next_steps."
    )
    return "\n".join(lines)


def analyse_session(state: SessionState, concepts: list[ConceptSpec]) -> GapReport:
    concept_weight_map = {c.name: c.pyq_weight for c in concepts}
    all_concepts = list(state.concept_coverage.keys()) or list(state.failure_mode_tally.keys())

    verdicts: list[ConceptVerdict] = []
    for concept in all_concepts:
        tally = state.failure_mode_tally.get(concept)
        mastery_pct = _compute_mastery_pct(state.difficulty_history, concept)
        verdict_str, dominant = _compute_verdict(tally, mastery_pct)
        low_confidence = bool(tally and 0 < tally.attempt_count < config.MASTERY_LOW_CONFIDENCE_MIN_ATTEMPTS)
        verdicts.append(
            ConceptVerdict(
                concept=concept,
                questions_asked=tally.attempt_count if tally else 0,
                correct=tally.correct_count if tally else 0,
                mastery_pct=mastery_pct,
                low_confidence=low_confidence,
                pyq_weight=concept_weight_map.get(concept, 0.0),
                verdict=verdict_str,
                dominant_failure_mode=dominant,
                reasoning="",  # filled by LLM below
            )
        )

    overall_score = sum(v.correct for v in verdicts)
    neet_score = _compute_neet_score(state.difficulty_history)
    bloom_dok_breakdown = _compute_bloom_dok_breakdown(state.difficulty_history)
    question_type_breakdown = _compute_question_type_breakdown(state.difficulty_history)
    error_analysis = _compute_error_analysis(state.failure_mode_tally)
    time_efficiency = _compute_time_efficiency(state.difficulty_history)
    time_efficiency.by_question_type = _compute_time_by_question_type(state.difficulty_history)
    recovery_progression = _compute_recovery_progression(state.difficulty_history)
    priority_concepts = _compute_priority_concepts(verdicts, state.failure_mode_tally)
    strength_concepts = _compute_strength_concepts(verdicts)
    question_history = _build_question_history(state.difficulty_history)

    summary = ""
    next_steps: list[str] = []
    try:
        llm_result = call_structured(
            _build_system_prompt(),
            _build_user_prompt(
                verdicts, neet_score, error_analysis, time_efficiency, recovery_progression,
                priority_concepts, strength_concepts, state.difficulty_history,
            ),
            GapAnalyserLLMResult,
        )
        narration_map = {n.concept: n for n in llm_result.concept_narrations}
        for v in verdicts:
            entry = narration_map.get(v.concept)
            v.reasoning = entry.reasoning if entry else ""
        summary = llm_result.summary
        next_steps = llm_result.next_steps

        for p in priority_concepts:
            entry = narration_map.get(p.concept)
            p.misconception_note = entry.misconception_note if entry else ""

        for s in strength_concepts:
            entry = narration_map.get(s.concept)
            s.expertise_note = entry.expertise_note if entry else ""
    except AgentGenerationError:
        logger.warning("Gap analyser LLM call failed; using fallback narrations")
        for v in verdicts:
            v.reasoning = f"Verdict: {v.verdict}. {v.correct}/{v.questions_asked} correct."
        summary = (
            f"Session complete. NEET score: {neet_score.raw_score}/{neet_score.max_score_from_attempted}. "
            f"Dominant error type: {_dominant_error_type(error_analysis)}. "
            "Review the concept breakdown for details."
        )
        next_steps = [
            f"Review {p.concept} (weak, PYQ weight {p.pyq_weight:.1f})" for p in priority_concepts[:3]
        ] or ["Review your concept breakdown below for areas to improve."]

    return GapReport(
        session_id=state.session_id,
        subject=state.subject,
        chapter=state.chapter,
        overall_score=overall_score,
        ability_estimate_final=state.ability_estimate,
        concept_verdicts=verdicts,
        neet_score=neet_score,
        bloom_dok_breakdown=bloom_dok_breakdown,
        question_type_breakdown=question_type_breakdown,
        error_analysis=error_analysis,
        time_efficiency=time_efficiency,
        recovery_progression=recovery_progression,
        priority_concepts=priority_concepts,
        strength_concepts=strength_concepts,
        question_history=question_history,
        summary=summary,
        next_steps=next_steps,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
