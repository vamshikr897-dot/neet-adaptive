from typing import Literal

from pydantic import BaseModel


class ConceptVerdict(BaseModel):
    concept: str
    questions_asked: int
    correct: int
    mastery_pct: float | None  # None only when questions_asked == 0
    low_confidence: bool  # True when questions_asked < config.MASTERY_LOW_CONFIDENCE_MIN_ATTEMPTS
    pyq_weight: float
    verdict: Literal["strong", "weak", "needs_improvement", "not_assessed"]
    dominant_failure_mode: Literal["conceptual_gap", "calculation_error", "exception_not_known", "none"]
    reasoning: str


class NeetScore(BaseModel):
    questions_attempted: int
    questions_unattempted: int
    correct_count: int
    incorrect_attempted_count: int
    raw_score: int  # +4/-1/0 sum
    max_score_from_attempted: int  # 4 * questions_attempted
    score_percentage: float | None  # None when questions_attempted == 0
    marks_lost_to_negative_marking: int  # == incorrect_attempted_count


class LevelBreakdownEntry(BaseModel):
    level: int
    attempted: int
    correct: int
    accuracy_pct: float


class BloomDokBreakdown(BaseModel):
    bloom: list[LevelBreakdownEntry]  # ascending by level, only levels encountered
    dok: list[LevelBreakdownEntry]


class ErrorAnalysis(BaseModel):
    conceptual_gap_count: int
    calculation_error_count: int
    exception_not_known_count: int
    total_incorrect_attempted: int
    conceptual_gap_pct: float | None
    calculation_error_pct: float | None
    exception_not_known_pct: float | None


class TimeEfficiency(BaseModel):
    avg_actual_seconds: float | None
    avg_expected_seconds: float | None
    efficiency_ratio: float | None  # None when questions_attempted == 0
    hesitation_index: float | None
    faster_bucket_accuracy_pct: float | None
    slower_bucket_accuracy_pct: float | None
    faster_bucket_count: int
    slower_bucket_count: int
    tradeoff_tag: Literal[
        "rushing_costs_accuracy", "overthinking_without_gain", "well_balanced", "insufficient_data"
    ]
    is_heuristic: bool = True
    heuristic_note: str = (
        "Expected-time baselines are an approximation, not derived from official NEET timing data."
    )


class RecoveryProgression(BaseModel):
    recovery_rate: float | None  # None when there were no mistakes to recover from
    total_after_wrong: int
    correct_after_wrong: int
    progression_available: bool
    first_half_accuracy_pct: float | None
    second_half_accuracy_pct: float | None
    first_half_avg_difficulty: float | None
    second_half_avg_difficulty: float | None


class PriorityConcept(BaseModel):
    concept: str
    verdict: Literal["weak", "needs_improvement"]
    pyq_weight: float
    mastery_pct: float | None


class GapReport(BaseModel):
    session_id: str
    chapter: str
    overall_score: int
    ability_estimate_final: float
    concept_verdicts: list[ConceptVerdict]
    neet_score: NeetScore
    bloom_dok_breakdown: BloomDokBreakdown
    error_analysis: ErrorAnalysis
    time_efficiency: TimeEfficiency
    recovery_progression: RecoveryProgression
    priority_concepts: list[PriorityConcept]
    summary: str
    generated_at: str
