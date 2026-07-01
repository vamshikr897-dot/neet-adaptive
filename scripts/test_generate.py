"""Standalone script to validate the Generator agent before wiring it into the FSM.

Usage: venv/Scripts/python.exe scripts/test_generate.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.generator import generate_batch
from models.agent_io import ConceptSpec

CASES = [
    {
        "subject": "Physics",
        "chapter": "Laws of Motion",
        "concept": ConceptSpec(name="Newton's Laws & Friction", pyq_weight=4.0),
        "difficulty_targets": [2, 3],
        "question_types": ["recall", "numerical"],
    },
    {
        "subject": "Botany",
        "chapter": "Cell Structure and Function",
        "concept": ConceptSpec(name="Cell Organelles", pyq_weight=4.0),
        "difficulty_targets": [2, 4],
        "question_types": ["recall", "exception"],
    },
]


def main():
    for case in CASES:
        print(f"\n=== {case['subject']} / {case['concept'].name} ===")
        try:
            questions = generate_batch(
                case["subject"], case["chapter"], case["concept"],
                case["difficulty_targets"], case["question_types"],
            )
        except Exception as e:
            print(f"FAILED: {e}")
            continue

        print(f"Got {len(questions)} valid question(s)")
        for q in questions:
            print(json.dumps(q.model_dump(), indent=2))


if __name__ == "__main__":
    main()
