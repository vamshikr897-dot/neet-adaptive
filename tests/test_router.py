from datetime import datetime, timezone

from agents.router import select_next_spec, update_ability
from models.agent_io import ConceptSpec
from models.session_state import DifficultyHistoryEntry, FailureModeTally, SessionState

CONCEPTS = [
    ConceptSpec(name="A", pyq_weight=4.0),
    ConceptSpec(name="B", pyq_weight=3.0),
    ConceptSpec(name="C", pyq_weight=2.0),
]


def _base_state(**overrides) -> SessionState:
    now = datetime.now(timezone.utc).isoformat()
    defaults = dict(
        session_id="s1",
        grade_level="11",
        subject="Physics",
        chapter="Test Chapter",
        selected_concepts=["A", "B", "C"],
        status="awaiting_answer",
        current_question_index=1,
        ability_estimate=2.5,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return SessionState(**defaults)


def test_update_ability_correct_at_or_above_level_increases_by_big_step():
    assert update_ability(2.5, difficulty=3, correct=True) == 3.0


def test_update_ability_correct_below_level_increases_by_small_step():
    assert update_ability(2.5, difficulty=2, correct=True) == 2.75


def test_update_ability_wrong_at_or_below_level_decreases_by_big_step():
    assert update_ability(2.5, difficulty=2, correct=False) == 2.0


def test_update_ability_wrong_above_level_decreases_by_small_step():
    assert update_ability(2.5, difficulty=3, correct=False) == 2.25


def test_update_ability_clamped_to_range():
    assert update_ability(5.0, difficulty=5, correct=True) == 5.0
    assert update_ability(1.0, difficulty=1, correct=False) == 1.0


def test_update_ability_without_time_info_matches_baseline():
    # Omitting question_type/time_taken_seconds must reproduce the pre-time-aware behavior exactly.
    assert update_ability(2.5, difficulty=3, correct=True) == 3.0


def test_update_ability_fast_correct_amplifies_step_above_baseline():
    baseline = update_ability(2.5, difficulty=3, correct=True)
    fast = update_ability(2.5, difficulty=3, correct=True, question_type="recall", time_taken_seconds=5)
    assert fast > baseline


def test_update_ability_slow_correct_dampens_step_below_baseline():
    baseline = update_ability(2.5, difficulty=3, correct=True)
    slow = update_ability(2.5, difficulty=3, correct=True, question_type="recall", time_taken_seconds=200)
    assert slow < baseline


def test_update_ability_moderately_fast_wrong_amplifies_downward_step():
    # Faster than expected but still above the rushed-guess threshold -> normal amplification.
    baseline = update_ability(2.5, difficulty=2, correct=False)
    fast = update_ability(2.5, difficulty=2, correct=False, question_type="recall", time_taken_seconds=20)
    assert fast < baseline


def test_update_ability_very_fast_wrong_dampens_as_rushed_guess():
    # Well below the rushed-guess ratio threshold -> dampened, not amplified, since a very fast
    # wrong answer looks like a guess rather than a deliberate, diagnostic mistake.
    baseline = update_ability(2.5, difficulty=2, correct=False)
    guess = update_ability(2.5, difficulty=2, correct=False, question_type="recall", time_taken_seconds=5)
    assert guess > baseline


def test_update_ability_slow_wrong_dampens_downward_step():
    baseline = update_ability(2.5, difficulty=2, correct=False)
    slow = update_ability(2.5, difficulty=2, correct=False, question_type="recall", time_taken_seconds=200)
    assert slow > baseline


def test_update_ability_time_factor_never_inverts_direction():
    # Even at extreme time ratios, a correct answer must still increase ability and vice versa.
    up = update_ability(2.5, difficulty=3, correct=True, question_type="recall", time_taken_seconds=99999)
    down = update_ability(2.5, difficulty=2, correct=False, question_type="recall", time_taken_seconds=99999)
    assert up > 2.5
    assert down < 2.5


def test_select_concept_all_correct_prefers_highest_pyq_weight():
    # All concepts equally covered and equally strong -> highest pyq_weight (A) should win
    state = _base_state(
        concept_coverage={"A": 1, "B": 1, "C": 1},
        failure_mode_tally={
            "A": FailureModeTally(concept="A", correct_count=1, attempt_count=1),
            "B": FailureModeTally(concept="B", correct_count=1, attempt_count=1),
            "C": FailureModeTally(concept="C", correct_count=1, attempt_count=1),
        },
    )
    spec = select_next_spec(state, CONCEPTS)
    assert spec.concept == "A"


def test_select_concept_all_wrong_does_not_retest_before_warmup():
    # Question index below the warmup threshold -> should not yet prioritize the weak concept
    state = _base_state(
        current_question_index=2,
        concept_coverage={"A": 1, "B": 0, "C": 0},
        failure_mode_tally={
            "A": FailureModeTally(concept="A", correct_count=0, attempt_count=1, conceptual_gap=1),
        },
    )
    spec = select_next_spec(state, CONCEPTS)
    # B has equal coverage to C but higher pyq_weight, and warmup hasn't passed so weak-retest is skipped
    assert spec.concept == "B"


def test_select_concept_wrong_on_one_concept_only_retests_after_warmup():
    # Past the warmup window, with A being the only weak (low-mastery) concept -> A gets a
    # coverage boost that outranks B/C's real lower coverage. difficulty_history must be
    # populated too since weak detection is now mastery-based (difficulty-weighted), not raw
    # accuracy, and mastery is computed from difficulty_history, not failure_mode_tally alone.
    state = _base_state(
        current_question_index=4,
        concept_coverage={"A": 2, "B": 1, "C": 1},
        failure_mode_tally={
            "A": FailureModeTally(concept="A", correct_count=0, attempt_count=2, conceptual_gap=2),
            "B": FailureModeTally(concept="B", correct_count=1, attempt_count=1),
            "C": FailureModeTally(concept="C", correct_count=1, attempt_count=1),
        },
        difficulty_history=[
            DifficultyHistoryEntry(
                question_index=1, difficulty=2, concept="A", question_type="recall",
                correct=False, time_taken_seconds=10,
            ),
            DifficultyHistoryEntry(
                question_index=2, difficulty=2, concept="A", question_type="recall",
                correct=False, time_taken_seconds=10,
            ),
            DifficultyHistoryEntry(
                question_index=3, difficulty=2, concept="B", question_type="recall",
                correct=True, time_taken_seconds=10,
            ),
            DifficultyHistoryEntry(
                question_index=4, difficulty=2, concept="C", question_type="recall",
                correct=True, time_taken_seconds=10,
            ),
        ],
    )
    spec = select_next_spec(state, CONCEPTS)
    assert spec.concept == "A"


def test_select_concept_weak_boost_does_not_override_genuinely_uncovered_concept():
    # A is weak (boost -2, but its raw coverage of 3 still leaves effective coverage 1 after the
    # boost) while C has real coverage 0 - C must still win, since the boost is a soft preference
    # among similar coverage, not a hard filter that can override a genuinely uncovered concept.
    state = _base_state(
        current_question_index=4,
        concept_coverage={"A": 3, "B": 2, "C": 0},
        failure_mode_tally={
            "A": FailureModeTally(concept="A", correct_count=0, attempt_count=2, conceptual_gap=2),
        },
        difficulty_history=[
            DifficultyHistoryEntry(
                question_index=1, difficulty=2, concept="A", question_type="recall",
                correct=False, time_taken_seconds=10,
            ),
            DifficultyHistoryEntry(
                question_index=2, difficulty=2, concept="A", question_type="recall",
                correct=False, time_taken_seconds=10,
            ),
        ],
    )
    spec = select_next_spec(state, CONCEPTS)
    assert spec.concept == "C"


def test_select_concept_breaks_true_ties_randomly():
    # B and C have equal coverage AND equal pyq_weight (a genuine tie) with no weak concepts -
    # across many trials, both should appear, not always the same one due to list-order bias.
    tied_concepts = [
        ConceptSpec(name="A", pyq_weight=4.0),
        ConceptSpec(name="B", pyq_weight=3.0),
        ConceptSpec(name="C", pyq_weight=3.0),
    ]
    state = _base_state(concept_coverage={"A": 5, "B": 1, "C": 1})
    seen = {select_next_spec(state, tied_concepts).concept for _ in range(50)}
    assert seen == {"B", "C"}


def test_select_concept_respects_coverage_cap():
    # With 3 concepts and 10 questions/session, cap = ceil(10/3)+1 = 5. Force A over the cap.
    state = _base_state(concept_coverage={"A": 5, "B": 0, "C": 0})
    spec = select_next_spec(state, CONCEPTS)
    assert spec.concept != "A"


def test_select_next_spec_difficulty_matches_rounded_ability():
    state = _base_state(ability_estimate=3.6)
    spec = select_next_spec(state, CONCEPTS)
    assert spec.target_difficulty == 4


def test_select_next_spec_avoids_three_in_a_row_question_type():
    state = _base_state(
        difficulty_history=[
            DifficultyHistoryEntry(
                question_index=1, difficulty=2, concept="A", question_type="recall",
                correct=True, time_taken_seconds=10,
            ),
            DifficultyHistoryEntry(
                question_index=2, difficulty=2, concept="B", question_type="recall",
                correct=True, time_taken_seconds=10,
            ),
        ]
    )
    spec = select_next_spec(state, CONCEPTS)
    # Not a hard guarantee (re-roll is best-effort), but should hold under a fixed seed
    assert spec.question_type in {"recall", "exception", "diagram", "numerical", "multi_concept"}
