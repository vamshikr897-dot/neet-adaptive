from unittest.mock import patch

from agents.generator import _has_numeric_collision, _numeric_signature, generate_batch
from models.agent_io import ConceptSpec
from models.question import DistractorRationale, QuestionDraft, QuestionDraftBatch


def _rationale():
    return [
        DistractorRationale(option_key="A", is_correct=True, misconception_tag="correct", explanation="right"),
        DistractorRationale(option_key="B", is_correct=False, misconception_tag="wrong_b", explanation="wrong"),
        DistractorRationale(option_key="C", is_correct=False, misconception_tag="wrong_c", explanation="wrong"),
        DistractorRationale(option_key="D", is_correct=False, misconception_tag="wrong_d", explanation="wrong"),
    ]


def _draft(stem: str) -> QuestionDraft:
    return QuestionDraft(
        stem=stem,
        options={"A": "opt A", "B": "opt B", "C": "opt C", "D": "opt D"},
        correct_option="A",
        distractor_rationale=_rationale(),
        pyq_similarity_note="note",
        solution_steps="steps",
    )


def test_numeric_signature_extracts_and_sorts_numbers():
    assert _numeric_signature("A 5 kg mass moves at 10 m/s") == ("10", "5")


def test_numeric_signature_ignores_extra_numbers_beyond_six():
    stem = "1 2 3 4 5 6 7 8"
    assert len(_numeric_signature(stem)) == 6


def test_has_numeric_collision_true_for_matching_signature():
    existing = [_numeric_signature("A 5 kg mass moves at 10 m/s")]
    assert _has_numeric_collision("A block of 10 kg accelerates from 5 m/s", existing) is True


def test_has_numeric_collision_false_for_different_numbers():
    existing = [_numeric_signature("A 5 kg mass moves at 10 m/s")]
    assert _has_numeric_collision("A 7 kg mass moves at 12 m/s", existing) is False


def test_has_numeric_collision_false_with_fewer_than_two_numbers():
    existing = [_numeric_signature("A 5 kg mass moves at 10 m/s")]
    assert _has_numeric_collision("A mass moves at 10 m/s", existing) is False


def test_generate_batch_retries_discarded_duplicate_slot():
    concept = ConceptSpec(name="Circular Motion", pyq_weight=3.0)
    existing_stems = ["An already-stored question about circular motion basics."]

    # First call returns a duplicate (matches existing_stems) and a fine question.
    first_response = QuestionDraftBatch(questions=[
        _draft("An already-stored question about circular motion basics."),
        _draft("A genuinely new question about banking angles."),
    ])
    # Retry call (for the one discarded slot) returns a fresh, non-duplicate replacement.
    retry_response = QuestionDraftBatch(questions=[
        _draft("A completely different question about centripetal force."),
    ])

    with patch("agents.generator.call_structured", side_effect=[first_response, retry_response]) as mock_call:
        results = generate_batch(
            "Physics", "Laws of Motion", concept,
            difficulty_targets=[2, 3], question_types=["recall", "recall"],
            existing_stems=existing_stems,
        )

    assert mock_call.call_count == 2
    assert len(results) == 2
    stems = {q.stem for q in results}
    assert "A genuinely new question about banking angles." in stems
    assert "A completely different question about centripetal force." in stems
    assert "An already-stored question about circular motion basics." not in stems


def test_generate_batch_gives_up_after_retry_budget_exhausted():
    concept = ConceptSpec(name="Circular Motion", pyq_weight=3.0)
    existing_stems = ["Duplicate stem that will never be accepted."]

    # Every call (initial + both retries) returns the same duplicate - should give up cleanly
    # after _retries_left is exhausted rather than looping forever.
    always_duplicate = QuestionDraftBatch(questions=[_draft("Duplicate stem that will never be accepted.")])

    with patch("agents.generator.call_structured", return_value=always_duplicate) as mock_call:
        results = generate_batch(
            "Physics", "Laws of Motion", concept,
            difficulty_targets=[2], question_types=["recall"],
            existing_stems=existing_stems,
        )

    assert results == []
    assert mock_call.call_count == 3  # initial attempt + 2 retries
