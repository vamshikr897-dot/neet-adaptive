import uuid
from unittest.mock import patch

import pytest

import config
import db
from agents.ollama_client import AgentGenerationError
from models.question import DistractorRationale, QuestionSchema
from orchestrator import state_machine
from repositories import question_repo

SUBJECT = "Physics"
GRADE = "11"
CONCEPT_NAMES = ["Test Concept A", "Test Concept B"]
DIFFICULTIES = [1, 2, 3, 4, 5]
TYPES = ["recall", "exception", "numerical", "diagram", "multi_concept"]


def _rationale():
    return [
        DistractorRationale(option_key="A", is_correct=True, misconception_tag="correct", explanation="right"),
        DistractorRationale(option_key="B", is_correct=False, misconception_tag="wrong_b", explanation="wrong"),
        DistractorRationale(option_key="C", is_correct=False, misconception_tag="wrong_c", explanation="wrong"),
        DistractorRationale(option_key="D", is_correct=False, misconception_tag="wrong_d", explanation="wrong"),
    ]


def _question(chapter, concept, difficulty, qtype, idx) -> QuestionSchema:
    return QuestionSchema(
        subject=SUBJECT, chapter=chapter, concept=concept, question_type=qtype, difficulty=difficulty,
        bloom_level=2, dok_level=1,
        stem=f"Stem {concept} {qtype} d{difficulty} #{idx}",
        options={"A": "opt A", "B": "opt B", "C": "opt C", "D": "opt D"},
        correct_option="A",
        distractor_rationale=_rationale(),
        pyq_similarity_note="note",
        solution_steps="steps",
    )


@pytest.fixture
def seeded_chapter():
    """Creates a throwaway chapter+concepts and a fully-stocked question pool (every
    difficulty x question_type combo) so the router/generator relaxation logic always finds a
    match and the test never triggers a real LLM call."""
    db.init_db()
    chapter_name = f"Test Chapter {uuid.uuid4().hex[:8]}"

    conn = db.get_connection()
    conn.execute("INSERT OR IGNORE INTO subjects (name) VALUES (?)", (SUBJECT,))
    conn.commit()
    subject_id = conn.execute("SELECT subject_id FROM subjects WHERE name = ?", (SUBJECT,)).fetchone()["subject_id"]

    conn.execute(
        "INSERT INTO chapters (subject_id, grade_level, name, display_order) VALUES (?, ?, ?, 0)",
        (subject_id, GRADE, chapter_name),
    )
    conn.commit()
    chapter_id = conn.execute(
        "SELECT chapter_id FROM chapters WHERE subject_id = ? AND grade_level = ? AND name = ?",
        (subject_id, GRADE, chapter_name),
    ).fetchone()["chapter_id"]

    concept_ids = []
    for name in CONCEPT_NAMES:
        conn.execute("INSERT INTO concepts (chapter_id, name, pyq_weight) VALUES (?, ?, ?)", (chapter_id, name, 4.0))
        conn.commit()
        concept_ids.append(
            conn.execute(
                "SELECT concept_id FROM concepts WHERE chapter_id = ? AND name = ?", (chapter_id, name)
            ).fetchone()["concept_id"]
        )
    conn.close()

    questions = [
        _question(chapter_name, concept, difficulty, qtype, idx)
        for idx, (concept, difficulty, qtype) in enumerate(
            (c, d, t) for c in CONCEPT_NAMES for d in DIFFICULTIES for t in TYPES
        )
    ]
    question_repo.insert_questions(questions, source="pool")

    yield {"grade_level": GRADE, "subject": SUBJECT, "chapter": chapter_name, "concepts": CONCEPT_NAMES}

    conn = db.get_connection()
    conn.execute("DELETE FROM question_bank WHERE chapter = ?", (chapter_name,))
    for cid in concept_ids:
        conn.execute("DELETE FROM concepts WHERE concept_id = ?", (cid,))
    conn.execute("DELETE FROM chapters WHERE chapter_id = ?", (chapter_id,))
    conn.commit()
    conn.close()


def _cleanup_session(session_id: str) -> None:
    conn = db.get_connection()
    conn.execute("DELETE FROM gap_reports WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM attempts WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


def _run_full_session(seeded_chapter) -> str:
    result = state_machine.start_new(
        seeded_chapter["grade_level"], seeded_chapter["subject"], seeded_chapter["chapter"], []
    )
    session_id = result["session_id"]
    status = result["status"]
    count = 0
    while status == "awaiting_answer" and count < config.SESSION_SAFETY_CAP:
        result = state_machine.submit_answer(session_id, "A", 15.0)  # every dummy question's correct_option
        status = result["status"]
        count += 1
    assert count <= config.SESSION_SAFETY_CAP
    assert status == "complete"
    return session_id


def test_full_session_lifecycle_reaches_completion(seeded_chapter):
    session_id = _run_full_session(seeded_chapter)
    try:
        state = state_machine.get_state(session_id)
        for concept in seeded_chapter["concepts"]:
            covered = state.concept_coverage.get(concept, 0)
            unique_diffs = {e.difficulty for e in state.difficulty_history if e.concept == concept}
            # Either genuine mastery termination was reached for every concept, or the session
            # safety cap kicked in first - both are valid ways for _mastery_reached to return True.
            assert (
                covered >= config.MIN_QUESTIONS_PER_CONCEPT and len(unique_diffs) >= config.MIN_DIFF_LEVELS_PER_CONCEPT
            ) or state.current_question_index >= config.SESSION_SAFETY_CAP
    finally:
        _cleanup_session(session_id)


def test_complete_session_report_is_idempotent(seeded_chapter):
    session_id = _run_full_session(seeded_chapter)
    try:
        report1 = state_machine.complete_session_report(session_id)
        report2 = state_machine.complete_session_report(session_id)
        assert report1 == report2
    finally:
        _cleanup_session(session_id)


def test_complete_session_report_raises_when_not_complete(seeded_chapter):
    result = state_machine.start_new(
        seeded_chapter["grade_level"], seeded_chapter["subject"], seeded_chapter["chapter"], []
    )
    session_id = result["session_id"]
    try:
        with pytest.raises(state_machine.SessionNotCompleteError):
            state_machine.complete_session_report(session_id)
    finally:
        _cleanup_session(session_id)


def test_unknown_session_id_raises_session_not_found():
    fake_id = str(uuid.uuid4())
    with pytest.raises(state_machine.SessionNotFoundError):
        state_machine.get_current(fake_id)
    with pytest.raises(state_machine.SessionNotFoundError):
        state_machine.submit_answer(fake_id, "A", 10.0)
    with pytest.raises(state_machine.SessionNotFoundError):
        state_machine.complete_session_report(fake_id)


def test_serve_question_falls_back_to_repeat_when_generation_fails(seeded_chapter):
    # Exhaust every pre-stocked question for one concept (mark all as already-asked) so
    # _find_question_with_relaxation must fall through to live generation, then force that
    # generation to fail - the serve step should fall back to repeating an already-asked
    # question instead of raising, since one genuinely exists for the concept.
    concept = seeded_chapter["concepts"][0]
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT question_id FROM question_bank WHERE chapter = ? AND concept = ?",
        (seeded_chapter["chapter"], concept),
    ).fetchall()
    conn.close()
    all_ids = [r["question_id"] for r in rows]
    assert all_ids

    from models.agent_io import QuestionSpec
    from models.session_state import SessionState
    from repositories import session_repo

    state = SessionState(
        session_id=str(uuid.uuid4()), grade_level=GRADE, subject=SUBJECT, chapter=seeded_chapter["chapter"],
        selected_concepts=[], status="awaiting_answer", ability_estimate=2.5,
        asked_question_ids=all_ids, created_at="2024-01-01T00:00:00Z", updated_at="2024-01-01T00:00:00Z",
    )
    session_repo.create(state)  # create_attempt() below has an FK on sessions.session_id
    spec = QuestionSpec(concept=concept, question_type="recall", target_difficulty=2)

    try:
        with patch("agents.generator.generate_single_question", side_effect=AgentGenerationError("llm down")):
            record = state_machine._serve_question(state, spec)
        assert record["concept"] == concept
    finally:
        _cleanup_session(state.session_id)


def test_serve_question_raises_question_unavailable_when_pool_truly_empty():
    from models.agent_io import QuestionSpec
    from models.session_state import SessionState

    state = SessionState(
        session_id=str(uuid.uuid4()), grade_level=GRADE, subject=SUBJECT, chapter="No Such Chapter",
        selected_concepts=[], status="awaiting_answer", ability_estimate=2.5,
        created_at="2024-01-01T00:00:00Z", updated_at="2024-01-01T00:00:00Z",
    )
    spec = QuestionSpec(concept="Nonexistent Concept", question_type="recall", target_difficulty=2)

    with patch("agents.generator.generate_single_question", side_effect=AgentGenerationError("llm down")):
        with pytest.raises(state_machine.QuestionUnavailableError):
            state_machine._serve_question(state, spec)
