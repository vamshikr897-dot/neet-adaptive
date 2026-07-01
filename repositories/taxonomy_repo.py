import db


def get_grade_levels() -> list[str]:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT grade_level FROM chapters ORDER BY grade_level"
        ).fetchall()
        return [row["grade_level"] for row in rows]
    finally:
        conn.close()


def get_chapters(grade_level: str, subject: str | None = None) -> list[dict]:
    conn = db.get_connection()
    try:
        query = """
            SELECT c.chapter_id, c.name AS chapter, c.display_order, s.name AS subject
            FROM chapters c
            JOIN subjects s ON s.subject_id = c.subject_id
            WHERE c.grade_level = ?
        """
        params: list = [grade_level]
        if subject:
            query += " AND s.name = ?"
            params.append(subject)
        query += " ORDER BY s.name, c.display_order"

        chapter_rows = conn.execute(query, params).fetchall()

        chapters = []
        for row in chapter_rows:
            concept_rows = conn.execute(
                "SELECT name, pyq_weight FROM concepts WHERE chapter_id = ? ORDER BY pyq_weight DESC",
                (row["chapter_id"],),
            ).fetchall()
            chapters.append(
                {
                    "subject": row["subject"],
                    "chapter": row["chapter"],
                    "concepts": [
                        {"name": c["name"], "pyq_weight": c["pyq_weight"]}
                        for c in concept_rows
                    ],
                }
            )
        return chapters
    finally:
        conn.close()


def get_chapter_concepts(grade_level: str, subject: str, chapter: str) -> list[dict]:
    conn = db.get_connection()
    try:
        chapter_row = conn.execute(
            """
            SELECT c.chapter_id FROM chapters c
            JOIN subjects s ON s.subject_id = c.subject_id
            WHERE c.grade_level = ? AND s.name = ? AND c.name = ?
            """,
            (grade_level, subject, chapter),
        ).fetchone()
        if not chapter_row:
            return []
        concept_rows = conn.execute(
            "SELECT name, pyq_weight FROM concepts WHERE chapter_id = ? ORDER BY pyq_weight DESC",
            (chapter_row["chapter_id"],),
        ).fetchall()
        return [{"name": c["name"], "pyq_weight": c["pyq_weight"]} for c in concept_rows]
    finally:
        conn.close()
