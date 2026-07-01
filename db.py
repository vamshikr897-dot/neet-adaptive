import sqlite3

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS subjects (
    subject_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS chapters (
    chapter_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id    INTEGER NOT NULL REFERENCES subjects(subject_id),
    grade_level   TEXT NOT NULL,
    name          TEXT NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE(subject_id, grade_level, name)
);

CREATE TABLE IF NOT EXISTS concepts (
    concept_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id   INTEGER NOT NULL REFERENCES chapters(chapter_id),
    name         TEXT NOT NULL,
    pyq_weight   REAL NOT NULL DEFAULT 1.0,
    UNIQUE(chapter_id, name)
);

CREATE TABLE IF NOT EXISTS question_bank (
    question_id     TEXT PRIMARY KEY,
    concept_id      INTEGER NOT NULL REFERENCES concepts(concept_id),
    subject         TEXT NOT NULL,
    chapter         TEXT NOT NULL,
    concept         TEXT NOT NULL,
    question_type   TEXT NOT NULL,
    difficulty      INTEGER NOT NULL,
    stem            TEXT NOT NULL,
    options_json    TEXT NOT NULL,
    correct_option  TEXT NOT NULL,
    distractor_rationale_json TEXT NOT NULL,
    pyq_similarity_note TEXT,
    solution_steps  TEXT,
    diagram_svg     TEXT NOT NULL DEFAULT '',
    source          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    used_count      INTEGER NOT NULL DEFAULT 0,
    bloom_level     INTEGER NOT NULL DEFAULT 0,
    dok_level       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_qbank_concept_diff ON question_bank(concept_id, difficulty);

CREATE TABLE IF NOT EXISTS sessions (
    session_id       TEXT PRIMARY KEY,
    grade_level      TEXT NOT NULL,
    subject          TEXT NOT NULL,
    chapter          TEXT NOT NULL,
    selected_concepts_json TEXT NOT NULL,
    status           TEXT NOT NULL,
    current_question_index INTEGER NOT NULL DEFAULT 0,
    ability_estimate REAL NOT NULL DEFAULT 2.5,
    state_json       TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attempts (
    attempt_id        TEXT PRIMARY KEY,
    session_id        TEXT NOT NULL REFERENCES sessions(session_id),
    question_id       TEXT NOT NULL REFERENCES question_bank(question_id),
    question_index    INTEGER NOT NULL,
    selected_option   TEXT,
    correct           INTEGER NOT NULL,
    time_taken_seconds REAL NOT NULL,
    failure_mode      TEXT,
    evaluator_reasoning TEXT,
    served_at         TEXT NOT NULL,
    answered_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_attempts_session ON attempts(session_id);

CREATE TABLE IF NOT EXISTS gap_reports (
    session_id              TEXT PRIMARY KEY REFERENCES sessions(session_id),
    overall_score           INTEGER NOT NULL,
    ability_estimate_final  REAL NOT NULL,
    concept_verdicts_json   TEXT NOT NULL,
    summary                 TEXT NOT NULL,
    generated_at             TEXT NOT NULL
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_question_bank(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(question_bank)")}
    if "diagram_svg" not in cols:
        conn.execute("ALTER TABLE question_bank ADD COLUMN diagram_svg TEXT NOT NULL DEFAULT ''")
    for col, ddl in (
        ("bloom_level", "ALTER TABLE question_bank ADD COLUMN bloom_level INTEGER NOT NULL DEFAULT 0"),
        ("dok_level",   "ALTER TABLE question_bank ADD COLUMN dok_level   INTEGER NOT NULL DEFAULT 0"),
    ):
        if col not in cols:
            conn.execute(ddl)
    conn.execute("""
        UPDATE question_bank
        SET
            bloom_level = CASE question_type
                WHEN 'recall'        THEN CASE WHEN difficulty <= 2 THEN 1 ELSE 2 END
                WHEN 'exception'     THEN 5
                WHEN 'numerical'     THEN 3
                WHEN 'diagram'       THEN 3
                WHEN 'multi_concept' THEN 4
                ELSE 2 END,
            dok_level = CASE question_type
                WHEN 'recall'        THEN 1
                WHEN 'exception'     THEN 2
                WHEN 'numerical'     THEN CASE WHEN difficulty >= 4 THEN 3 ELSE 2 END
                WHEN 'diagram'       THEN 2
                WHEN 'multi_concept' THEN 3
                ELSE 1 END
        WHERE bloom_level = 0 OR dok_level = 0
    """)
    conn.commit()


def _migrate_gap_reports(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(gap_reports)")}
    if "insights_json" not in cols:
        conn.execute("ALTER TABLE gap_reports ADD COLUMN insights_json TEXT NOT NULL DEFAULT '{}'")
    conn.commit()


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _migrate_question_bank(conn)
        _migrate_gap_reports(conn)
    finally:
        conn.close()
