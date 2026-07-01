import json

import config
import db


def seed() -> None:
    with open(config.TAXONOMY_PATH, encoding="utf-8") as f:
        taxonomy = json.load(f)

    conn = db.get_connection()
    try:
        for subject, chapters in taxonomy.items():
            conn.execute(
                "INSERT OR IGNORE INTO subjects (name) VALUES (?)", (subject,)
            )
            subject_id = conn.execute(
                "SELECT subject_id FROM subjects WHERE name = ?", (subject,)
            ).fetchone()["subject_id"]

            for order, (chapter_name, chapter_data) in enumerate(chapters.items()):
                grade_level = chapter_data["grade_level"]
                conn.execute(
                    """
                    INSERT OR IGNORE INTO chapters (subject_id, grade_level, name, display_order)
                    VALUES (?, ?, ?, ?)
                    """,
                    (subject_id, grade_level, chapter_name, order),
                )
                chapter_id = conn.execute(
                    """
                    SELECT chapter_id FROM chapters
                    WHERE subject_id = ? AND grade_level = ? AND name = ?
                    """,
                    (subject_id, grade_level, chapter_name),
                ).fetchone()["chapter_id"]

                for concept_name, pyq_weight in chapter_data["concepts"].items():
                    conn.execute(
                        """
                        INSERT INTO concepts (chapter_id, name, pyq_weight)
                        VALUES (?, ?, ?)
                        ON CONFLICT(chapter_id, name) DO UPDATE SET pyq_weight = excluded.pyq_weight
                        """,
                        (chapter_id, concept_name, pyq_weight),
                    )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    db.init_db()
    seed()
    print(f"Seeded taxonomy from {config.TAXONOMY_PATH} into {config.DB_PATH}")
