from agents.mastery import compute_mastery_pct
from models.session_state import DifficultyHistoryEntry


def _entry(concept, difficulty, correct):
    return DifficultyHistoryEntry(
        question_index=1, difficulty=difficulty, concept=concept, question_type="recall",
        correct=correct, time_taken_seconds=10.0,
    )


def test_compute_mastery_pct_empty_history_returns_none():
    assert compute_mastery_pct([], "X") is None


def test_compute_mastery_pct_concept_not_present_returns_none():
    history = [_entry("Y", 3, True)]
    assert compute_mastery_pct(history, "X") is None


def test_compute_mastery_pct_weighted_by_difficulty():
    # Correct at difficulty 4, wrong at difficulty 2 -> 4/(4+2) = 66.67%, not a plain 50% average.
    history = [_entry("X", 4, True), _entry("X", 2, False)]
    assert round(compute_mastery_pct(history, "X"), 2) == 66.67


def test_compute_mastery_pct_all_correct_is_100():
    history = [_entry("X", 3, True), _entry("X", 5, True)]
    assert compute_mastery_pct(history, "X") == 100.0
