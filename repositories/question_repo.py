import json
import random
import uuid
from datetime import datetime, timezone

import db
from models.question import QuestionSchema


def _get_concept_id(conn, subject: str, chapter: str, concept: str) -> int | None:
    row = conn.execute(
        """
        SELECT co.concept_id FROM concepts co
        JOIN chapters c ON c.chapter_id = co.chapter_id
        JOIN subjects s ON s.subject_id = c.subject_id
        WHERE s.name = ? AND c.name = ? AND co.name = ?
        """,
        (subject, chapter, concept),
    ).fetchone()
    return row["concept_id"] if row else None


def insert_questions(questions: list[QuestionSchema], source: str = "pool") -> list[str]:
    conn = db.get_connection()
    ids = []
    try:
        for q in questions:
            concept_id = _get_concept_id(conn, q.subject, q.chapter, q.concept)
            if concept_id is None:
                continue
            question_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO question_bank (
                    question_id, concept_id, subject, chapter, concept, question_type,
                    difficulty, stem, options_json, correct_option, distractor_rationale_json,
                    pyq_similarity_note, solution_steps, diagram_svg, source, created_at,
                    used_count, bloom_level, dok_level
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    question_id,
                    concept_id,
                    q.subject,
                    q.chapter,
                    q.concept,
                    q.question_type,
                    q.difficulty,
                    q.stem,
                    json.dumps(q.options),
                    q.correct_option,
                    json.dumps([r.model_dump() for r in q.distractor_rationale]),
                    q.pyq_similarity_note,
                    q.solution_steps,
                    q.diagram_svg,
                    source,
                    datetime.now(timezone.utc).isoformat(),
                    q.bloom_level,
                    q.dok_level,
                ),
            )
            ids.append(question_id)
        conn.commit()
    finally:
        conn.close()
    return ids


def _row_to_record(row) -> dict:
    return {
        "question_id": row["question_id"],
        "subject": row["subject"],
        "chapter": row["chapter"],
        "concept": row["concept"],
        "question_type": row["question_type"],
        "difficulty": row["difficulty"],
        "stem": row["stem"],
        "options": json.loads(row["options_json"]),
        "correct_option": row["correct_option"],
        "distractor_rationale": json.loads(row["distractor_rationale_json"]),
        "pyq_similarity_note": row["pyq_similarity_note"],
        "solution_steps": row["solution_steps"],
        "diagram_svg": row["diagram_svg"] or "",
        "source": row["source"],
        "used_count": row["used_count"],
        "bloom_level": row["bloom_level"],
        "dok_level": row["dok_level"],
    }


def get_by_id(question_id: str) -> dict | None:
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM question_bank WHERE question_id = ?", (question_id,)
        ).fetchone()
        return _row_to_record(row) if row else None
    finally:
        conn.close()


def find_matching(
    concept: str,
    difficulty: int | None = None,
    question_type: str | None = None,
    exclude_ids: list[str] | None = None,
) -> dict | None:
    exclude_ids = exclude_ids or []
    conn = db.get_connection()
    try:
        query = "SELECT * FROM question_bank WHERE concept = ?"
        params: list = [concept]
        if question_type:
            query += " AND question_type = ?"
            params.append(question_type)
        # Never serve a diagram question that has no SVG content
        query += " AND NOT (question_type = 'diagram' AND (diagram_svg IS NULL OR diagram_svg = ''))"
        if exclude_ids:
            query += f" AND question_id NOT IN ({','.join('?' for _ in exclude_ids)})"
            params.extend(exclude_ids)

        rows = conn.execute(query, params).fetchall()
        if not rows:
            return None

        if difficulty is not None:
            rows = sorted(rows, key=lambda r: (abs(r["difficulty"] - difficulty), r["used_count"]))
        else:
            rows = sorted(rows, key=lambda r: r["used_count"])

        return _row_to_record(random.choice(rows[:3]))
    finally:
        conn.close()


def mark_used(question_id: str) -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE question_bank SET used_count = used_count + 1 WHERE question_id = ?",
            (question_id,),
        )
        conn.commit()
    finally:
        conn.close()


def count_by_concept_difficulty(subject: str, chapter: str, concept: str) -> dict[int, int]:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT difficulty, COUNT(*) as n FROM question_bank
            WHERE subject = ? AND chapter = ? AND concept = ?
            GROUP BY difficulty
            """,
            (subject, chapter, concept),
        ).fetchall()
        return {row["difficulty"]: row["n"] for row in rows}
    finally:
        conn.close()
