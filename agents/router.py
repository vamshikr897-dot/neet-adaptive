import math
import random

import config
from agents.mastery import compute_mastery_pct
from agents.time_model import expected_time_seconds
from models.agent_io import ConceptSpec, QuestionSpec
from models.session_state import SessionState

ABILITY_STEP_BIG = 0.5
ABILITY_STEP_SMALL = 0.25
WEAK_RETEST_WARMUP_QUESTIONS = 3  # don't prioritize retesting weak concepts before this question index
COVERAGE_CAP_SLACK = 1  # extra allowance on top of the even-split cap

TYPE_WEIGHTS_BY_ABILITY = [
    (2.0, {"recall": 0.5, "exception": 0.2, "diagram": 0.15, "numerical": 0.1, "multi_concept": 0.05}),
    (3.5, {"recall": 0.3, "exception": 0.25, "diagram": 0.15, "numerical": 0.2, "multi_concept": 0.1}),
    (float("inf"), {"recall": 0.15, "exception": 0.25, "diagram": 0.15, "numerical": 0.25, "multi_concept": 0.2}),
]


def _time_confidence_factor(
    question_type: str | None, difficulty: int, time_taken_seconds: float | None, correct: bool
) -> float:
    """Scales the ability step by how the actual time compares to the expected pace.

    Correctness stays the primary signal - this only amplifies it (answered at or faster than
    expected -> more confidence in the observed outcome, whichever direction it points) or
    dampens it (answered slower than expected -> less confidence, since struggling to finish in
    time suggests the student is near the edge of their ability regardless of the outcome).
    Returns 1.0 (no change) when time data isn't available.

    Exception: a WRONG answer much faster than expected looks like a rushed guess rather than a
    deliberate, diagnostic mistake, so it dampens the (negative) step instead of amplifying it -
    a lucky/unlucky guess shouldn't swing the estimate as hard as a genuine wrong answer would.
    """
    if question_type is None or time_taken_seconds is None:
        return 1.0

    expected = expected_time_seconds(question_type, difficulty)
    ratio = time_taken_seconds / expected

    if not correct and ratio < config.GUESS_TIME_RATIO_THRESHOLD:
        return config.GUESS_DAMPING_FACTOR

    if ratio <= 1.0:
        bonus = config.TIME_CONFIDENCE_BONUS_MAX * (1.0 - ratio)
        return 1.0 + min(bonus, config.TIME_CONFIDENCE_BONUS_MAX)

    excess_range = config.TIME_RATIO_OUTLIER_CAP - 1.0
    excess = min(ratio - 1.0, excess_range)
    penalty = config.TIME_UNCERTAINTY_DAMPING_MAX * (excess / excess_range)
    return 1.0 - penalty


def update_ability(
    ability: float,
    difficulty: int,
    correct: bool,
    question_type: str | None = None,
    time_taken_seconds: float | None = None,
) -> float:
    time_factor = _time_confidence_factor(question_type, difficulty, time_taken_seconds, correct)
    if correct:
        step = ABILITY_STEP_BIG if difficulty >= ability else ABILITY_STEP_SMALL
        ability += step * time_factor
    else:
        step = ABILITY_STEP_BIG if difficulty <= ability else ABILITY_STEP_SMALL
        ability -= step * time_factor
    return max(config.MIN_DIFFICULTY, min(config.MAX_DIFFICULTY, ability))


def _target_difficulty(ability: float) -> int:
    return max(config.MIN_DIFFICULTY, min(config.MAX_DIFFICULTY, round(ability)))


def _select_concept(state: SessionState, available_concepts: list[ConceptSpec]) -> str:
    if not available_concepts:
        raise ValueError("available_concepts must not be empty")

    max_per_concept = math.ceil(config.QUESTIONS_PER_SESSION / len(available_concepts)) + COVERAGE_CAP_SLACK
    eligible = [
        c for c in available_concepts if state.concept_coverage.get(c.name, 0) < max_per_concept
    ] or available_concepts

    # Weak = difficulty-weighted mastery below the same threshold the report uses for a "weak"
    # verdict (not a separate raw-accuracy heuristic), so a concept flagged weak here matches
    # what the student will actually see as weak in their report.
    retest_active = state.current_question_index >= WEAK_RETEST_WARMUP_QUESTIONS
    weak_names = {
        c.name
        for c in eligible
        if (tally := state.failure_mode_tally.get(c.name))
        and tally.attempt_count > 0
        and (mastery := compute_mastery_pct(state.difficulty_history, c.name)) is not None
        and mastery < config.MASTERY_WEAK_THRESHOLD
    }

    def sort_key(c: ConceptSpec) -> tuple[int, float]:
        coverage = state.concept_coverage.get(c.name, 0)
        boost = config.WEAK_RETEST_COVERAGE_BOOST if (retest_active and c.name in weak_names) else 0
        # Weak concepts look "less covered" (up to the boost), so they're preferred in the
        # breadth-first ranking below without categorically excluding other concepts - a
        # genuinely uncovered concept (coverage 0) still outranks a boosted weak one.
        effective_coverage = max(0, coverage - boost)
        return (-effective_coverage, c.pyq_weight)

    # Breadth first (least-covered concept) with a weak-concept boost as above; pyq_weight only
    # breaks ties among equally-(effectively-)covered concepts - otherwise a single high-weight
    # concept would dominate the whole session. True ties are broken randomly, not by list order.
    best_score = max(sort_key(c) for c in eligible)
    best = [c for c in eligible if sort_key(c) == best_score]
    return random.choice(best).name


def _type_weights_for_ability(ability: float) -> dict[str, float]:
    for threshold, weights in TYPE_WEIGHTS_BY_ABILITY:
        if ability < threshold:
            return weights
    return TYPE_WEIGHTS_BY_ABILITY[-1][1]


def _select_question_type(state: SessionState) -> str:
    recent_types = [d.question_type for d in state.difficulty_history[-2:]]
    weights = _type_weights_for_ability(state.ability_estimate)

    for _attempt in range(2):
        types = list(weights.keys())
        probs = list(weights.values())
        choice = random.choices(types, weights=probs, k=1)[0]
        if len(recent_types) < 2 or not (recent_types[0] == recent_types[1] == choice):
            return choice
    return choice


def select_next_spec(state: SessionState, available_concepts: list[ConceptSpec]) -> QuestionSpec:
    concept = _select_concept(state, available_concepts)
    question_type = _select_question_type(state)
    target_difficulty = _target_difficulty(state.ability_estimate)
    return QuestionSpec(concept=concept, question_type=question_type, target_difficulty=target_difficulty)
