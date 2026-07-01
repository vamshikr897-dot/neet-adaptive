import config


def expected_time_seconds(question_type: str, difficulty: int) -> float:
    """Heuristic expected time for a question - NOT derived from official NEET timing data.
    Shared by the router (real-time ability updates) and the gap analyser (post-session report)
    so both use one definition of "expected pace" rather than two formulas that could drift."""
    base = config.EXPECTED_TIME_BASE_SECONDS[question_type]
    return base * (1 + config.EXPECTED_TIME_DIFFICULTY_MULTIPLIER_STEP * (difficulty - 1))
