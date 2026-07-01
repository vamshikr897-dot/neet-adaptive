from pydantic import BaseModel


class DifficultyHistoryEntry(BaseModel):
    question_index: int
    difficulty: int
    concept: str
    question_type: str
    correct: bool
    time_taken_seconds: float
    selected_option: str | None = None  # None means unattempted/timeout
    bloom_level: int = 0
    dok_level: int = 0


class FailureModeTally(BaseModel):
    concept: str
    conceptual_gap: int = 0
    calculation_error: int = 0
    exception_not_known: int = 0
    correct_count: int = 0
    attempt_count: int = 0


class SessionState(BaseModel):
    session_id: str
    grade_level: str
    subject: str
    chapter: str
    selected_concepts: list[str]
    status: str
    current_question_index: int = 0
    ability_estimate: float = 2.5
    difficulty_history: list[DifficultyHistoryEntry] = []
    concept_coverage: dict[str, int] = {}
    failure_mode_tally: dict[str, FailureModeTally] = {}
    asked_question_ids: list[str] = []
    current_question_id: str | None = None
    current_question_started_at: str | None = None
    created_at: str
    updated_at: str
