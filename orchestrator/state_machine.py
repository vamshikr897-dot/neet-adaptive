import logging
import random
import threading
import uuid
from datetime import datetime, timezone

import config

logger = logging.getLogger("neet_adaptive.state_machine")
from agents import evaluator, gap_analyser, generator, router
from agents.ollama_client import AgentGenerationError
from models.agent_io import ConceptSpec, QuestionSpec
from models.question import QuestionPublic
from models.report import GapReport
from models.session_state import DifficultyHistoryEntry, FailureModeTally, SessionState
from orchestrator.states import SessionStatus
from repositories import question_repo, report_repo, session_repo, taxonomy_repo


class SessionNotFoundError(Exception):
    pass


class SessionNotCompleteError(Exception):
    pass


class QuestionUnavailableError(Exception):
    pass


# Session IDs whose background pool-fill (_ensure_pool) hasn't finished yet - a lightweight,
# process-local signal (no DB persistence needed) so the frontend can show "still preparing
# questions" instead of an unexplained delay if just-in-time generation is later triggered.
_pool_generation_in_progress: set[str] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def available_concepts(state: SessionState) -> list[ConceptSpec]:
    all_concepts = taxonomy_repo.get_chapter_concepts(state.grade_level, state.subject, state.chapter)
    concepts = [ConceptSpec(name=c["name"], pyq_weight=c["pyq_weight"]) for c in all_concepts]
    if state.selected_concepts:
        concepts = [c for c in concepts if c.name in state.selected_concepts]
    return concepts


def _ensure_pool(state: SessionState, concepts: list[ConceptSpec], min_per_concept: int | None = None) -> None:
    """Generates questions only for concepts below min_per_concept (defaults to POOL_QUESTIONS_PER_CONCEPT)."""
    try:
        target = min_per_concept if min_per_concept is not None else config.POOL_QUESTIONS_PER_CONCEPT
        to_generate = []
        for concept in concepts:
            existing = question_repo.count_by_concept_difficulty(state.subject, state.chapter, concept.name)
            existing_count = sum(existing.values())
            if existing_count < target:
                to_generate.append(concept)

        if to_generate:
            try:
                questions = generator.generate_pool(
                    state.subject, state.chapter, to_generate, questions_per_concept=target
                )
                question_repo.insert_questions(questions, source="pool")
            except Exception:
                logger.exception("Background pool generation failed")
    finally:
        _pool_generation_in_progress.discard(state.session_id)


def _mastery_reached(state: SessionState, concepts: list[ConceptSpec]) -> bool:
    """True when every concept has >= MIN_QUESTIONS_PER_CONCEPT attempts at >= MIN_DIFF_LEVELS distinct difficulties."""
    if state.current_question_index >= config.SESSION_SAFETY_CAP:
        return True
    for c in concepts:
        if state.concept_coverage.get(c.name, 0) < config.MIN_QUESTIONS_PER_CONCEPT:
            return False
        unique_diffs = {e.difficulty for e in state.difficulty_history if e.concept == c.name}
        if len(unique_diffs) < config.MIN_DIFF_LEVELS_PER_CONCEPT:
            return False
    return True


def _find_question_with_relaxation(
    concept: str, difficulty: int, question_type: str, exclude_ids: list[str]
) -> dict | None:
    record = question_repo.find_matching(concept, difficulty, question_type, exclude_ids)
    if record:
        return record
    record = question_repo.find_matching(concept, difficulty, None, exclude_ids)
    if record:
        return record
    return question_repo.find_matching(concept, None, None, exclude_ids)


def _serve_question(state: SessionState, spec: QuestionSpec) -> dict:
    record = _find_question_with_relaxation(
        spec.concept, spec.target_difficulty, spec.question_type, state.asked_question_ids
    )
    if record is None:
        try:
            concept_spec = ConceptSpec(name=spec.concept, pyq_weight=1.0)
            question = generator.generate_single_question(
                state.subject, state.chapter, concept_spec, spec.target_difficulty, spec.question_type
            )
            ids = question_repo.insert_questions([question], source="just_in_time")
            record = question_repo.get_by_id(ids[0])
        except (AgentGenerationError, ValueError):
            # Live generation failed (LLM unavailable or produced nothing usable) - fall back to
            # repeating an already-asked question for this concept rather than crashing the
            # request. Only raise if literally nothing exists for the concept at all.
            logger.warning(
                "Just-in-time generation failed for concept=%s, falling back to a repeat question",
                spec.concept,
            )
            record = question_repo.find_matching(spec.concept, None, None, exclude_ids=[])
            if record is None:
                raise QuestionUnavailableError(spec.concept)

    question_repo.mark_used(record["question_id"])
    state.current_question_id = record["question_id"]
    state.current_question_started_at = _now()
    state.asked_question_ids.append(record["question_id"])
    session_repo.create_attempt(
        session_id=state.session_id,
        question_id=record["question_id"],
        question_index=state.current_question_index + 1,
        served_at=state.current_question_started_at,
    )
    return record


def get_state(session_id: str) -> SessionState | None:
    return session_repo.get(session_id)


def complete_session_report(session_id: str) -> GapReport:
    state = session_repo.get(session_id)
    if state is None:
        raise SessionNotFoundError(session_id)
    if state.status not in (SessionStatus.COMPLETE, SessionStatus.DONE):
        raise SessionNotCompleteError(session_id)

    existing = report_repo.get(session_id)
    if existing:
        return existing

    state.status = SessionStatus.GAP_ANALYSIS
    session_repo.save(state)

    concepts = available_concepts(state)
    report = gap_analyser.analyse_session(state, concepts)
    report_repo.insert(report)

    state.status = SessionStatus.DONE
    session_repo.save(state)
    return report


def start_new(grade_level: str, subject: str, chapter: str, selected_concepts: list[str]) -> dict:
    now = _now()
    state = SessionState(
        session_id=str(uuid.uuid4()),
        grade_level=grade_level,
        subject=subject,
        chapter=chapter,
        selected_concepts=selected_concepts,
        status=SessionStatus.GENERATING_POOL,
        ability_estimate=config.STARTING_ABILITY,
        created_at=now,
        updated_at=now,
    )
    session_repo.create(state)

    concepts = available_concepts(state)
    if not concepts:
        raise ValueError(f"No concepts found for {subject}/{chapter}/{grade_level}")

    first_concept = random.choices(concepts, weights=[c.pyq_weight for c in concepts], k=1)[0]
    first_spec = QuestionSpec(
        concept=first_concept.name, question_type="recall", target_difficulty=config.STARTING_DIFFICULTY
    )
    record = _serve_question(state, first_spec)
    state.current_question_index = 1
    state.status = SessionStatus.AWAITING_ANSWER
    session_repo.save(state)

    # Stage 2 (background): fill the full pool while user answers the first question. Marked
    # in-progress *before* the thread starts so the response below always reflects reality.
    _pool_generation_in_progress.add(state.session_id)
    threading.Thread(
        target=_ensure_pool,
        args=(state, concepts),
        daemon=True,
    ).start()

    return {
        "session_id": state.session_id,
        "question": QuestionPublic.from_record(record).model_dump(),
        "question_index": state.current_question_index,
        "safety_cap": config.SESSION_SAFETY_CAP,
        "status": state.status,
        "pool_ready": state.session_id not in _pool_generation_in_progress,
    }


def get_current(session_id: str) -> dict:
    state = session_repo.get(session_id)
    if state is None:
        raise SessionNotFoundError(session_id)
    pool_ready = session_id not in _pool_generation_in_progress
    if state.current_question_id is None:
        return {
            "question": None, "question_index": state.current_question_index,
            "safety_cap": config.SESSION_SAFETY_CAP, "status": state.status, "pool_ready": pool_ready,
        }
    record = question_repo.get_by_id(state.current_question_id)
    return {
        "question": QuestionPublic.from_record(record).model_dump(),
        "question_index": state.current_question_index,
        "safety_cap": config.SESSION_SAFETY_CAP,
        "status": state.status,
        "pool_ready": pool_ready,
    }


def submit_answer(session_id: str, selected_option: str | None, time_taken_seconds: float) -> dict:
    state = session_repo.get(session_id)
    if state is None:
        raise SessionNotFoundError(session_id)

    state.status = SessionStatus.EVALUATING
    question = question_repo.get_by_id(state.current_question_id)
    result = evaluator.evaluate_answer(question, selected_option)

    attempts = session_repo.get_attempts(session_id)
    current_attempt = next(
        a for a in attempts if a["question_id"] == question["question_id"] and a["answered_at"] is None
    )
    session_repo.record_answer(
        current_attempt["attempt_id"], selected_option, result.correct, time_taken_seconds,
        None if result.correct else result.failure_mode, result.reasoning,
    )

    concept = question["concept"]
    state.concept_coverage[concept] = state.concept_coverage.get(concept, 0) + 1
    tally = state.failure_mode_tally.get(concept) or FailureModeTally(concept=concept)
    tally.attempt_count += 1
    if result.correct:
        tally.correct_count += 1
    elif selected_option is not None and result.failure_mode != "none":
        # Unattempted (timeout) answers get failure_mode="conceptual_gap" from the evaluator as a
        # deterministic fallback, but there's no actual misconception to tally - only attempted
        # wrong answers reflect a real failure mode.
        setattr(tally, result.failure_mode, getattr(tally, result.failure_mode) + 1)
    state.failure_mode_tally[concept] = tally

    state.difficulty_history.append(
        DifficultyHistoryEntry(
            question_index=state.current_question_index,
            difficulty=question["difficulty"],
            concept=concept,
            question_type=question["question_type"],
            correct=result.correct,
            time_taken_seconds=time_taken_seconds,
            selected_option=selected_option,
            bloom_level=question["bloom_level"],
            dok_level=question["dok_level"],
            rationale_tag=result.rationale_tag,
            rationale_explanation=result.rationale_explanation,
        )
    )
    state.ability_estimate = router.update_ability(
        state.ability_estimate,
        question["difficulty"],
        result.correct,
        question_type=question["question_type"],
        time_taken_seconds=time_taken_seconds,
    )

    response = {
        "correct": result.correct,
        "correct_option": question["correct_option"],
        "failure_mode": None if result.correct else result.failure_mode,
        "reasoning": result.reasoning,
        "solution_steps": question.get("solution_steps") or "",
        "distractor_rationale": question["distractor_rationale"],
        "question_index": state.current_question_index,
    }

    concepts = available_concepts(state)
    if _mastery_reached(state, concepts):
        state.status = SessionStatus.COMPLETE
        state.current_question_id = None
        response["next_question"] = None
        response["status"] = state.status
    else:
        state.status = SessionStatus.ROUTING
        spec = router.select_next_spec(state, concepts)
        record = _serve_question(state, spec)
        state.current_question_index += 1
        state.status = SessionStatus.AWAITING_ANSWER
        response["next_question"] = QuestionPublic.from_record(record).model_dump()
        response["status"] = state.status
        response["question_index"] = state.current_question_index

    response["pool_ready"] = session_id not in _pool_generation_in_progress
    session_repo.save(state)
    return response
