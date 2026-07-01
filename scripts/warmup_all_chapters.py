"""Pre-warm question bank and validate the complete flow for all 19 chapters.

Phase 1 — for each chapter, generates POOL_QUESTIONS_PER_CONCEPT questions per concept
           (skips concepts that already have enough questions in the DB).
Phase 2 — for each chapter, starts a session and submits Q1 to verify end-to-end routing.
Phase 3 — prints a summary table with timing and pass/fail per chapter.

Usage:
    venv\\Scripts\\python.exe scripts/warmup_all_chapters.py            # pre-warm + verify
    venv\\Scripts\\python.exe scripts/warmup_all_chapters.py --verify-only  # flow check only
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from agents import generator
from models.agent_io import ConceptSpec
from orchestrator import state_machine
from repositories import question_repo, taxonomy_repo

REQUIRED_PER_CONCEPT = config.POOL_QUESTIONS_PER_CONCEPT


def prewarm_chapter(
    subject: str, chapter: str, concepts: list[ConceptSpec]
) -> tuple[int, int]:
    """Generate missing questions for all concepts in this chapter.

    Returns (newly_inserted, already_full_count).
    """
    to_generate = []
    for c in concepts:
        existing_count = sum(
            question_repo.count_by_concept_difficulty(subject, chapter, c.name).values()
        )
        if existing_count < REQUIRED_PER_CONCEPT:
            to_generate.append(c)
    if not to_generate:
        return 0, len(concepts)
    questions = generator.generate_pool(
        subject, chapter, to_generate, questions_per_concept=REQUIRED_PER_CONCEPT
    )
    inserted_ids = question_repo.insert_questions(questions, source="warmup")
    return len(inserted_ids), len(concepts) - len(to_generate)


def verify_chapter(
    grade_level: str, subject: str, chapter: str
) -> tuple[int | None, int | None, str | None]:
    """Start a session, serve Q1, submit Q1, verify Q2.

    Returns (q1_ms, q2_ms, error_message_or_None).
    """
    t0 = time.time()
    try:
        r1 = state_machine.start_new(grade_level, subject, chapter, selected_concepts=[])
        q1_ms = int((time.time() - t0) * 1000)

        question = r1["question"]
        if not question:
            return q1_ms, None, "Q1 is None"

        # QuestionPublic deliberately omits correct_option (never sent to the client
        # pre-answer) — fetch it from the full DB record for this verification-only submit.
        full_record = question_repo.get_by_id(question["question_id"])
        correct_option = full_record["correct_option"]

        # Submit the correct option — tests evaluator fast-path + routing
        t1 = time.time()
        r2 = state_machine.submit_answer(r1["session_id"], correct_option, 5.0)
        q2_ms = int((time.time() - t1) * 1000)

        status = r2.get("status")
        if status not in ("awaiting_answer", "complete"):
            return q1_ms, q2_ms, f"unexpected status after Q1: {status!r}"

        if status == "awaiting_answer" and not r2.get("next_question"):
            return q1_ms, q2_ms, "Q2 is None despite awaiting_answer status"

        return q1_ms, q2_ms, None

    except Exception as exc:
        elapsed_ms = int((time.time() - t0) * 1000)
        return elapsed_ms, None, str(exc)


def _fmt(ms: int | None) -> str:
    return f"{ms}ms" if ms is not None else "—"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Skip pool generation; only run flow verification",
    )
    args = parser.parse_args()

    rows: list[dict] = []
    total_generated = 0

    for grade in config.GRADE_LEVELS:
        chapters = taxonomy_repo.get_chapters(grade)
        for ch in chapters:
            subject = ch["subject"]
            chapter = ch["chapter"]
            concepts = [
                ConceptSpec(name=c["name"], pyq_weight=c["pyq_weight"])
                for c in ch["concepts"]
            ]

            label = f"{subject} / {chapter} (Gr {grade})"
            print(f"\n-- {label} --")
            print(f"   Concepts: {len(concepts)} ({', '.join(c.name for c in concepts)})")

            gen_count = 0
            if not args.verify_only:
                t = time.time()
                gen_count, already_full = prewarm_chapter(subject, chapter, concepts)
                elapsed = time.time() - t
                total_generated += gen_count
                print(
                    f"   Pre-warm: +{gen_count} new questions, "
                    f"{already_full} concepts already full  ({elapsed:.1f}s)"
                )

            q1_ms, q2_ms, err = verify_chapter(grade, subject, chapter)
            status_str = "OK" if err is None else f"FAIL  {err}"
            print(f"   Flow:     Q1={_fmt(q1_ms)}  Q2={_fmt(q2_ms)}  {status_str}")

            rows.append(
                dict(
                    label=f"{subject[:8]}/{chapter[:30]}",
                    grade=grade,
                    gen=gen_count,
                    q1=q1_ms,
                    q2=q2_ms,
                    ok=err is None,
                    err=err or "",
                )
            )

    # ── Summary table ──────────────────────────────────────────────────────────
    passed = sum(1 for r in rows if r["ok"])
    failed = len(rows) - passed

    print(f"\n{'=' * 72}")
    print(f"SUMMARY  {passed}/{len(rows)} chapters passed   {total_generated} questions generated")
    print(f"{'-' * 72}")
    print(f"{'Chapter':<42} {'Gr':>2}  {'New Qs':>6}  {'Q1':>7}  {'Q2':>7}  Status")
    print(f"{'-' * 72}")
    for r in rows:
        status_sym = "OK" if r["ok"] else "FAIL"
        print(
            f"{r['label']:<42} {r['grade']:>2}  "
            f"{r['gen']:>6}  {_fmt(r['q1']):>7}  {_fmt(r['q2']):>7}  {status_sym}"
        )

    if failed:
        print(f"\n{'-' * 72}")
        print("FAILURES:")
        for r in rows:
            if not r["ok"]:
                print(f"  {r['label']} (Gr {r['grade']}): {r['err']}")

    print(f"\n{'=' * 72}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
