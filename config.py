import os

from dotenv import load_dotenv

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:120b")

DB_PATH = os.getenv("DB_PATH", "./data/neet.db")
TAXONOMY_PATH = os.getenv("TAXONOMY_PATH", "./data/taxonomy.json")
LLM_CALL_LOG_PATH = os.getenv("LLM_CALL_LOG_PATH", "./data/llm_call_log.jsonl")

SUBJECTS = ["Physics", "Chemistry", "Botany", "Zoology"]
GRADE_LEVELS = ["11", "12"]
QUESTION_TYPES = ["recall", "exception", "diagram", "numerical", "multi_concept"]

GENERATOR_BATCH_SIZE = int(os.getenv("GENERATOR_BATCH_SIZE", 3))
POOL_QUESTIONS_PER_CONCEPT = int(os.getenv("POOL_QUESTIONS_PER_CONCEPT", 4))
QUESTIONS_PER_SESSION = int(os.getenv("QUESTIONS_PER_SESSION", 10))  # kept for router coverage-cap

# Adaptive session termination
MIN_QUESTIONS_PER_CONCEPT   = int(os.getenv("MIN_QUESTIONS_PER_CONCEPT", 3))
MIN_DIFF_LEVELS_PER_CONCEPT = int(os.getenv("MIN_DIFF_LEVELS_PER_CONCEPT", 2))
SESSION_SAFETY_CAP          = int(os.getenv("SESSION_SAFETY_CAP", 30))

MIN_DIFFICULTY = 1
MAX_DIFFICULTY = 5
STARTING_DIFFICULTY = 2
STARTING_ABILITY = 2.5

# Report metric thresholds
MASTERY_STRONG_THRESHOLD = 75.0
MASTERY_WEAK_THRESHOLD = 50.0
MASTERY_LOW_CONFIDENCE_MIN_ATTEMPTS = 5

PRIORITY_CONCEPT_PYQ_WEIGHT_MIN = 3.5

SPEED_ACCURACY_GAP_THRESHOLD_PCT = 15.0
TIME_RATIO_OUTLIER_CAP = 5.0
HESITATION_TIME_RATIO_THRESHOLD = 1.5

# Router ability-update time modulation: correctness stays the dominant signal, time only
# scales the step by up to +/- this fraction (faster-than-expected amplifies, slower dampens).
TIME_CONFIDENCE_BONUS_MAX = 0.3
TIME_UNCERTAINTY_DAMPING_MAX = 0.3

PROGRESSION_MIN_QUESTIONS = 4

# NEET marking scheme
NEET_CORRECT_MARKS = 4
NEET_INCORRECT_MARKS = -1

# Time-efficiency heuristic - NOT derived from official NEET per-question timing data
# (see TimeEfficiency.heuristic_note in models/report.py). Keys must match QUESTION_TYPES.
EXPECTED_TIME_BASE_SECONDS = {
    "recall": 30,
    "exception": 45,
    "numerical": 60,
    "diagram": 60,
    "multi_concept": 70,
}
EXPECTED_TIME_DIFFICULTY_MULTIPLIER_STEP = 0.15  # expected_time *= 1 + STEP * (difficulty - 1)
