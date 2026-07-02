from models.session_state import DifficultyHistoryEntry


def compute_mastery_pct(history: list[DifficultyHistoryEntry], concept: str) -> float | None:
    entries = [e for e in history if e.concept == concept]
    if not entries:
        return None
    total_difficulty = sum(e.difficulty for e in entries)
    if total_difficulty == 0:
        return None
    correct_difficulty = sum(e.difficulty for e in entries if e.correct)
    return 100.0 * correct_difficulty / total_difficulty
