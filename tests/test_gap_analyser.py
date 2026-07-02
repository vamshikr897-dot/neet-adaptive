import json
import uuid
from datetime import datetime, timezone

import pytest

import db
from agents.gap_analyser import (
    _build_question_history,
    _collect_rationale_notes,
    _compute_bloom_dok_breakdown,
    _compute_priority_concepts,
    _compute_question_type_breakdown,
    _compute_strength_concepts,
    _compute_time_by_question_type,
    _compute_time_efficiency,
)
from models.report import (
    BloomDokBreakdown,
    ConceptVerdict,
    ErrorAnalysis,
    GapReport,
    NeetScore,
    QuestionHistoryPoint,
    QuestionTypeBreakdownEntry,
    RecoveryProgression,
    TimeEfficiency,
)
from models.session_state import DifficultyHistoryEntry, FailureModeTally
from repositories import report_repo


def _entry(
    question_index, correct=True, selected_option="A", difficulty=2, concept="X",
    time_taken=10.0, question_type="recall", rationale_tag=None, rationale_explanation=None,
):
    return DifficultyHistoryEntry(
        question_index=question_index,
        difficulty=difficulty,
        concept=concept,
        question_type=question_type,
        correct=correct,
        time_taken_seconds=time_taken,
        selected_option=selected_option,
        bloom_level=1,
        dok_level=1,
        rationale_tag=rationale_tag,
        rationale_explanation=rationale_explanation,
    )


def _verdict(concept, verdict, pyq_weight=4.0, mastery_pct=50.0, correct=2, questions_asked=4):
    return ConceptVerdict(
        concept=concept, questions_asked=questions_asked, correct=correct, mastery_pct=mastery_pct,
        low_confidence=False, pyq_weight=pyq_weight, verdict=verdict,
        dominant_failure_mode="conceptual_gap" if verdict != "strong" else "none", reasoning="",
    )


def test_build_question_history_sorts_by_question_index_regardless_of_input_order():
    history = [_entry(3), _entry(1), _entry(2)]
    result = _build_question_history(history)
    assert [p.question_index for p in result] == [1, 2, 3]


def test_build_question_history_empty_input_returns_empty_list():
    assert _build_question_history([]) == []


def test_build_question_history_marks_unattempted_correctly():
    history = [_entry(1, selected_option="A"), _entry(2, selected_option=None, correct=False)]
    result = _build_question_history(history)
    assert result[0].attempted is True
    assert result[1].attempted is False


def test_bloom_dok_breakdown_excludes_unattempted_questions():
    history = [
        _entry(1, selected_option="A"),
        _entry(2, selected_option="B"),
        _entry(3, selected_option=None, correct=False),  # skipped/timed-out
    ]
    breakdown = _compute_bloom_dok_breakdown(history)
    assert sum(e.attempted for e in breakdown.bloom) == 2
    assert sum(e.attempted for e in breakdown.dok) == 2


def test_bloom_dok_breakdown_excludes_level_zero_legacy_entries():
    history = [
        _entry(1, selected_option="A"),
        DifficultyHistoryEntry(
            question_index=2, difficulty=2, concept="X", question_type="recall",
            correct=True, time_taken_seconds=10.0, selected_option="A",
            bloom_level=0, dok_level=0,
        ),
    ]
    breakdown = _compute_bloom_dok_breakdown(history)
    assert sum(e.attempted for e in breakdown.bloom) == 1
    assert sum(e.attempted for e in breakdown.dok) == 1


def test_question_type_breakdown_excludes_unattempted_questions():
    history = [
        _entry(1, selected_option="A", question_type="recall"),
        _entry(2, selected_option="B", question_type="numerical"),
        _entry(3, selected_option=None, correct=False, question_type="recall"),  # skipped/timed-out
    ]
    breakdown = _compute_question_type_breakdown(history)
    assert sum(e.attempted for e in breakdown) == 2


def test_question_type_breakdown_groups_by_type_in_canonical_order():
    history = [
        _entry(1, question_type="numerical", correct=True),
        _entry(2, question_type="numerical", correct=False),
        _entry(3, question_type="recall", correct=True),
        _entry(4, question_type="diagram", correct=True),
    ]
    breakdown = _compute_question_type_breakdown(history)
    # canonical order from generator._TYPE_CYCLE: recall, exception, numerical, diagram, multi_concept
    assert [e.question_type for e in breakdown] == ["recall", "numerical", "diagram"]
    numerical_entry = next(e for e in breakdown if e.question_type == "numerical")
    assert numerical_entry.attempted == 2
    assert numerical_entry.correct == 1
    assert numerical_entry.accuracy_pct == 50.0


def test_priority_concepts_includes_failure_breakdown_from_tally():
    verdicts = [_verdict("Weak Concept", "weak", pyq_weight=4.0)]
    tally = {"Weak Concept": FailureModeTally(
        concept="Weak Concept", conceptual_gap=2, calculation_error=1, exception_not_known=0,
        correct_count=2, attempt_count=4,
    )}
    result = _compute_priority_concepts(verdicts, tally)
    assert len(result) == 1
    assert result[0].conceptual_gap == 2
    assert result[0].calculation_error == 1
    assert result[0].exception_not_known == 0


def test_priority_concepts_still_excludes_below_pyq_floor():
    verdicts = [_verdict("Low Weight Weak", "weak", pyq_weight=1.0)]
    result = _compute_priority_concepts(verdicts, {})
    assert result == []


def test_strength_concepts_includes_only_strong_verdicts_sorted_by_pyq_weight():
    verdicts = [
        _verdict("A", "strong", pyq_weight=2.0),
        _verdict("B", "weak", pyq_weight=5.0),
        _verdict("C", "strong", pyq_weight=4.0),
    ]
    result = _compute_strength_concepts(verdicts)
    assert [s.concept for s in result] == ["C", "A"]


def test_collect_rationale_notes_filters_by_concept_and_correctness():
    history = [
        _entry(1, concept="X", correct=False, rationale_explanation="forgot friction term"),
        _entry(2, concept="X", correct=True, rationale_explanation="correctly applied Newton's law"),
        _entry(3, concept="Y", correct=False, rationale_explanation="wrong concept entirely"),
    ]
    wrong_notes = _collect_rationale_notes(history, "X", want_correct=False)
    correct_notes = _collect_rationale_notes(history, "X", want_correct=True)
    assert wrong_notes == ["forgot friction term"]
    assert correct_notes == ["correctly applied Newton's law"]


def test_time_efficiency_counts_rushed_guesses():
    history = [
        # Well under 30% of the ~30s expected time for a difficulty-1 recall question, and wrong.
        _entry(1, correct=False, difficulty=1, time_taken=5.0),
        # Wrong but not suspiciously fast - not a rushed guess.
        _entry(2, correct=False, difficulty=1, time_taken=25.0),
        # Fast but correct - not a rushed guess (that's the hesitation index's opposite case).
        _entry(3, correct=True, difficulty=1, time_taken=5.0),
    ]
    result = _compute_time_efficiency(history)
    assert result.rushed_guess_count == 1


def test_time_by_question_type_groups_and_averages_in_canonical_order():
    history = [
        _entry(1, question_type="numerical", time_taken=20.0),
        _entry(2, question_type="numerical", time_taken=40.0),
        _entry(3, question_type="recall", time_taken=10.0),
        _entry(4, selected_option=None, question_type="recall", time_taken=999.0),  # excluded
    ]
    result = _compute_time_by_question_type(history)
    assert [e.question_type for e in result] == ["recall", "numerical"]
    numerical_entry = next(e for e in result if e.question_type == "numerical")
    assert numerical_entry.avg_actual_seconds == 30.0
    assert numerical_entry.count == 2


@pytest.fixture
def fake_session_row():
    db.init_db()
    session_id = f"test-gap-analyser-{uuid.uuid4()}"
    now = datetime.now(timezone.utc).isoformat()
    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO sessions (
            session_id, grade_level, subject, chapter, selected_concepts_json,
            status, current_question_index, ability_estimate, state_json, created_at, updated_at
        ) VALUES (?, '11', 'Physics', 'Test Chapter', '[]', 'done', 1, 2.5, '{}', ?, ?)
        """,
        (session_id, now, now),
    )
    conn.commit()
    conn.close()
    yield session_id
    conn = db.get_connection()
    conn.execute("DELETE FROM gap_reports WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


def _minimal_gap_report(session_id: str, question_history: list[QuestionHistoryPoint]) -> GapReport:
    return GapReport(
        session_id=session_id,
        subject="Physics",
        chapter="Test Chapter",
        overall_score=1,
        ability_estimate_final=2.5,
        concept_verdicts=[],
        neet_score=NeetScore(
            questions_attempted=1,
            questions_unattempted=0,
            correct_count=1,
            incorrect_attempted_count=0,
            raw_score=4,
            max_score_from_attempted=4,
            score_percentage=100.0,
            marks_lost_to_negative_marking=0,
        ),
        bloom_dok_breakdown=BloomDokBreakdown(bloom=[], dok=[]),
        question_type_breakdown=[
            QuestionTypeBreakdownEntry(question_type="recall", attempted=1, correct=1, accuracy_pct=100.0)
        ],
        error_analysis=ErrorAnalysis(
            conceptual_gap_count=0,
            calculation_error_count=0,
            exception_not_known_count=0,
            total_incorrect_attempted=0,
            conceptual_gap_pct=None,
            calculation_error_pct=None,
            exception_not_known_pct=None,
        ),
        time_efficiency=TimeEfficiency(
            avg_actual_seconds=None,
            avg_expected_seconds=None,
            efficiency_ratio=None,
            hesitation_index=None,
            faster_bucket_accuracy_pct=None,
            slower_bucket_accuracy_pct=None,
            faster_bucket_count=0,
            slower_bucket_count=0,
            tradeoff_tag="insufficient_data",
        ),
        recovery_progression=RecoveryProgression(
            recovery_rate=None,
            total_after_wrong=0,
            correct_after_wrong=0,
            progression_available=False,
            first_half_accuracy_pct=None,
            second_half_accuracy_pct=None,
            first_half_avg_difficulty=None,
            second_half_avg_difficulty=None,
        ),
        priority_concepts=[],
        strength_concepts=[],
        question_history=question_history,
        summary="test summary",
        next_steps=["test next step"],
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def test_report_repo_round_trip_preserves_question_history(fake_session_row):
    session_id = fake_session_row
    qh = [
        QuestionHistoryPoint(
            question_index=1, time_taken_seconds=12.5, correct=True,
            difficulty=3, concept="Newton's Laws", attempted=True,
        )
    ]
    report_repo.insert(_minimal_gap_report(session_id, qh))
    fetched = report_repo.get(session_id)
    assert fetched is not None
    assert fetched.question_history == qh


def test_report_repo_get_returns_none_for_row_missing_question_history_key(fake_session_row):
    session_id = fake_session_row
    qh = [
        QuestionHistoryPoint(
            question_index=1, time_taken_seconds=5.0, correct=False,
            difficulty=2, concept="X", attempted=True,
        )
    ]
    report_repo.insert(_minimal_gap_report(session_id, qh))

    # Simulate a pre-existing row from before the question_history key existed.
    conn = db.get_connection()
    row = conn.execute("SELECT insights_json FROM gap_reports WHERE session_id=?", (session_id,)).fetchone()
    insights = json.loads(row["insights_json"])
    del insights["question_history"]
    conn.execute(
        "UPDATE gap_reports SET insights_json=? WHERE session_id=?", (json.dumps(insights), session_id)
    )
    conn.commit()
    conn.close()

    assert report_repo.get(session_id) is None
