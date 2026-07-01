import json
import uuid
from datetime import datetime, timezone

import db
from models.session_state import SessionState


def create(state: SessionState) -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO sessions (
                session_id, grade_level, subject, chapter, selected_concepts_json,
                status, current_question_index, ability_estimate, state_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state.session_id, state.grade_level, state.subject, state.chapter,
                json.dumps(state.selected_concepts), state.status, state.current_question_index,
                state.ability_estimate, state.model_dump_json(), state.created_at, state.updated_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def save(state: SessionState) -> None:
    state.updated_at = datetime.now(timezone.utc).isoformat()
    conn = db.get_connection()
    try:
        conn.execute(
            """
            UPDATE sessions SET
                status = ?, current_question_index = ?, ability_estimate = ?,
                state_json = ?, updated_at = ?
            WHERE session_id = ?
            """,
            (
                state.status, state.current_question_index, state.ability_estimate,
                state.model_dump_json(), state.updated_at, state.session_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get(session_id: str) -> SessionState | None:
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT state_json FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return SessionState.model_validate_json(row["state_json"]) if row else None
    finally:
        conn.close()


def create_attempt(session_id: str, question_id: str, question_index: int, served_at: str) -> str:
    attempt_id = str(uuid.uuid4())
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO attempts (
                attempt_id, session_id, question_id, question_index, selected_option,
                correct, time_taken_seconds, failure_mode, evaluator_reasoning, served_at, answered_at
            ) VALUES (?, ?, ?, ?, NULL, 0, 0, NULL, NULL, ?, NULL)
            """,
            (attempt_id, session_id, question_id, question_index, served_at),
        )
        conn.commit()
    finally:
        conn.close()
    return attempt_id


def record_answer(
    attempt_id: str,
    selected_option: str | None,
    correct: bool,
    time_taken_seconds: float,
    failure_mode: str | None,
    evaluator_reasoning: str,
) -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            """
            UPDATE attempts SET
                selected_option = ?, correct = ?, time_taken_seconds = ?,
                failure_mode = ?, evaluator_reasoning = ?, answered_at = ?
            WHERE attempt_id = ?
            """,
            (
                selected_option, int(correct), time_taken_seconds, failure_mode,
                evaluator_reasoning, datetime.now(timezone.utc).isoformat(), attempt_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_attempts(session_id: str) -> list[dict]:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM attempts WHERE session_id = ? ORDER BY question_index", (session_id,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
