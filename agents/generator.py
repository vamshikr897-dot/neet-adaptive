import json
import logging

import config
from agents.ollama_client import call_structured
from models.agent_io import ConceptSpec
from models.question import QuestionDraftBatch, QuestionSchema

logger = logging.getLogger("neet_adaptive.generator")

_DIFFICULTY_CYCLE = [2, 3, 4, 3, 2, 4, 1, 3, 5, 3]
_TYPE_CYCLE = ["recall", "exception", "numerical", "diagram", "multi_concept"]

# Few-shot examples only show the generative content fields (stem/options/rationale/etc) -
# subject/chapter/concept/difficulty/question_type are described in prose context instead,
# since those fields are never trusted from the model's restatement (see QuestionDraft).
_DIAGRAM_SVG_EXAMPLE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 180"'
    ' style="background:#fff;font-family:sans-serif;font-size:10px">'
    '<line x1="20" y1="20" x2="280" y2="20" stroke="#333" stroke-width="2"/>'
    '<line x1="20" y1="160" x2="280" y2="160" stroke="#333" stroke-width="2"/>'
    # Left battery E1
    '<line x1="20" y1="20" x2="20" y2="70" stroke="#333" stroke-width="2"/>'
    '<line x1="12" y1="70" x2="28" y2="70" stroke="#333" stroke-width="3"/>'
    '<line x1="15" y1="80" x2="25" y2="80" stroke="#333" stroke-width="1.5"/>'
    '<line x1="20" y1="80" x2="20" y2="160" stroke="#333" stroke-width="2"/>'
    '<text x="30" y="78">E₁=6V, r₁=1Ω</text>'
    # Common resistor R in the centre
    '<line x1="150" y1="20" x2="150" y2="65" stroke="#333" stroke-width="2"/>'
    '<rect x="138" y="65" width="24" height="50" fill="#fafafa" stroke="#333" stroke-width="2"/>'
    '<text x="140" y="95">R=2Ω</text>'
    '<line x1="150" y1="115" x2="150" y2="160" stroke="#333" stroke-width="2"/>'
    # Right battery E2
    '<line x1="280" y1="20" x2="280" y2="70" stroke="#333" stroke-width="2"/>'
    '<line x1="272" y1="70" x2="288" y2="70" stroke="#333" stroke-width="3"/>'
    '<line x1="275" y1="80" x2="285" y2="80" stroke="#333" stroke-width="1.5"/>'
    '<line x1="280" y1="80" x2="280" y2="160" stroke="#333" stroke-width="2"/>'
    '<text x="170" y="78">E₂=3V, r₂=1Ω</text>'
    '</svg>'
)

FEW_SHOT_EXAMPLES: dict[str, dict] = {
    "Zoology": {
        "context": "NEET Zoology / Human Physiology / Neural Control & Coordination / question_type=exception / difficulty=3",
        "draft": {
            "bloom_level": 5,
            "dok_level": 2,
            "stem": "Which of the following statements about the resting membrane potential of a neuron is NOT correct?",
            "options": {
                "A": "The axoplasm is electronegative compared to the outside of the membrane",
                "B": "The membrane is more permeable to K+ than to Na+ at rest",
                "C": "Resting potential is typically around -70 mV",
                "D": "The Na+-K+ pump moves both ions down their concentration gradients",
            },
            "correct_option": "D",
            "distractor_rationale": [
                {"option_key": "A", "is_correct": False, "misconception_tag": "correct_fact", "explanation": "This is true at rest, so a student who picks this has misread the question as asking for a TRUE statement."},
                {"option_key": "B", "is_correct": False, "misconception_tag": "correct_fact", "explanation": "True at rest due to leak channels; picking this suggests misreading the NOT-correct framing."},
                {"option_key": "C", "is_correct": False, "misconception_tag": "correct_fact", "explanation": "True; -70mV is the standard resting value taught in NCERT."},
                {"option_key": "D", "is_correct": True, "misconception_tag": "na_k_pump_active_transport_confusion", "explanation": "The Na+-K+ pump moves ions AGAINST their concentration gradients (active transport, uses ATP) — this statement is false, making it the correct answer to a NOT-correct question."},
            ],
            "pyq_similarity_note": "Matches the recurring NEET pattern of assertion-style exception questions on neuron resting/action potential mechanics.",
            "solution_steps": "",
        },
    },
    "Physics": {
        "context": "NEET Physics / Laws of Motion / Newton's Laws & Friction / question_type=numerical / difficulty=3",
        "draft": {
            "bloom_level": 3,
            "dok_level": 2,
            "stem": "A block of mass 4 kg rests on a horizontal surface with coefficient of friction 0.25. A horizontal force of 15 N is applied. What is the acceleration of the block? (g = 10 m/s^2)",
            "options": {
                "A": "1.25 m/s^2",
                "B": "2.5 m/s^2",
                "C": "3.75 m/s^2",
                "D": "0 m/s^2 (block does not move)",
            },
            "correct_option": "A",
            "distractor_rationale": [
                {"option_key": "A", "is_correct": True, "misconception_tag": "correct", "explanation": "Friction force = 0.25*4*10 = 10N; net force = 15-10 = 5N; a = 5/4 = 1.25 m/s^2."},
                {"option_key": "B", "is_correct": False, "misconception_tag": "forgot_to_subtract_friction", "explanation": "15/4 = 2.5 — forgot to subtract friction before dividing by mass (calculation_error)."},
                {"option_key": "C", "is_correct": False, "misconception_tag": "sign_error_friction", "explanation": "Added friction instead of subtracting: (15+10)/4 ~ wrong sign handling on the friction force (calculation_error)."},
                {"option_key": "D", "is_correct": False, "misconception_tag": "confuses_static_with_kinetic_threshold", "explanation": "Assumes applied force can't overcome friction, ignoring that 15N > max static-like friction of 10N (conceptual_gap)."},
            ],
            "pyq_similarity_note": "Standard NEET friction-on-horizontal-surface numerical, frequently appears in Laws of Motion sets.",
            "solution_steps": "f=mu*N=0.25*4*10=10N; F_net=15-10=5N; a=F_net/m=5/4=1.25 m/s^2",
        },
    },
}


def _build_system_prompt(subject: str) -> str:
    example = FEW_SHOT_EXAMPLES.get(subject) or FEW_SHOT_EXAMPLES["Physics"]
    diagram_ex = {
        "context": "NEET Physics / Current Electricity / Kirchhoff's Laws & Circuits / question_type=diagram / difficulty=3",
        "draft": {
            "bloom_level": 3,
            "dok_level": 3,
            "stem": "A circuit consists of two loops sharing a common branch. The left loop has battery E₁ = 6 V with internal resistance r₁ = 1 Ω. The right loop has battery E₂ = 3 V with internal resistance r₂ = 1 Ω. The common branch contains resistor R = 2 Ω. Both batteries drive current clockwise in their respective loops. Using Kirchhoff's laws, the current through R is:",
            "options": {"A": "0.5 A", "B": "1.0 A", "C": "1.5 A", "D": "2.0 A"},
            "correct_option": "C",
            "distractor_rationale": [
                {"option_key": "A", "is_correct": False, "misconception_tag": "forgot_second_battery", "explanation": "Ignores E₂'s contribution."},
                {"option_key": "B", "is_correct": False, "misconception_tag": "ignored_internal_resistance", "explanation": "Omits r₁ and r₂ in loop equations."},
                {"option_key": "C", "is_correct": True, "misconception_tag": "correct", "explanation": "KVL on both loops gives I_R = 1.5 A."},
                {"option_key": "D", "is_correct": False, "misconception_tag": "sign_error_on_emf", "explanation": "Added EMFs without accounting for loop direction."},
            ],
            "pyq_similarity_note": "Two-loop Kirchhoff circuit is a standard NEET Physics item.",
            "solution_steps": "Loop 1: 6=3I₁-2I₂; Loop 2: 3=-2I₁+3I₂; solving gives I_R=1.5 A.",
            "diagram_svg": _DIAGRAM_SVG_EXAMPLE,
        },
    }
    return f"""You are an expert NEET (National Eligibility cum Entrance Test, India) question paper setter with
deep knowledge of NCERT Class 11/12 syllabus and a decade of previous-year NEET papers (NEET PYQs).

IMPORTANT: NEET's Biology section is split into two separate subjects, Botany (plant biology) and Zoology
(animal/human biology) - never use the generic label "Biology" anywhere in your response.

Write multiple-choice questions that match the rigor, phrasing conventions, and conceptual depth of actual
NEET PYQs - not generic trivia. Use NEET's characteristic question framings where appropriate (e.g. "which of
the following is NOT correct", assertion-reason style, numerical problems requiring 2-3 calculation steps).

question_type meanings:
- recall: direct factual recall from NCERT text
- exception: "which is NOT true / NOT correct" or identifying the odd-one-out
- diagram: Generate a diagram_svg field with compact inline SVG (viewBox="0 0 320 200", background:#fff, labelled).
  Use SVG for circuits, inclined planes, lens/mirror setups, force diagrams, ray diagrams, and simple
  geometric/physical setups — keep SVG under 800 chars. For complex biological or anatomical diagrams
  that cannot be simplified to SVG, set diagram_svg to "" and describe the setup clearly in the stem
  using "A circuit consists of…" / "A system has…" — NOT "the figure shows", "as shown", or "(not shown)".
- numerical: requires a calculation (physics/chemistry mostly)
- multi_concept: requires combining two related concepts to answer

For EVERY question, tag each of the 4 options (A-D) with a distractor_rationale entry explaining WHY a
student might pick it if wrong (a specific misconception_tag and explanation), and exactly one entry must
have is_correct=true matching correct_option.

For non-diagram questions set diagram_svg to "" (empty string).

Here is a worked example of the expected rigor and JSON shape (context: {example['context']}):
{json.dumps({**example["draft"], "diagram_svg": ""}, indent=2)}

For diagram questions, here is an additional example showing the diagram_svg field (context: {diagram_ex['context']}):
{json.dumps(diagram_ex["draft"], indent=2)}

Now write NEW, ORIGINAL questions for the requested concept and difficulty/type targets.
Difficulty scale: 1=easy direct recall, 2=easy-medium, 3=medium (typical NEET level), 4=hard, 5=very hard.

Bloom's Taxonomy cognitive level (bloom_level, integer 1-5):
  1=Remember (direct recall of a fact, definition, or formula)
  2=Understand (explain, classify, or paraphrase a concept)
  3=Apply (use a formula or procedure in a new scenario)
  4=Analyze (break down, compare, or connect multiple concepts)
  5=Evaluate (judge correctness, exception/"NOT correct" questions)
  Never use 6 for MCQs.

Webb's Depth of Knowledge (dok_level, integer 1-3):
  1=Recall & Reproduction (one fact/formula, no reasoning chain)
  2=Skills & Concepts (conceptual understanding + at least one procedural step)
  3=Strategic Thinking (multi-step reasoning, comparing structures/mechanisms)
  Never use 4 for MCQs.

Return ONLY a JSON object with a "questions" array - one entry per requested target, in order. Include ONLY
these content fields: bloom_level, dok_level, stem, options, correct_option, distractor_rationale, pyq_similarity_note, solution_steps, diagram_svg."""


def _build_user_prompt(chapter: str, concept: ConceptSpec, difficulty_targets: list[int], question_types: list[str]) -> str:
    targets = ", ".join(
        f"(difficulty={d}, question_type={t})" for d, t in zip(difficulty_targets, question_types)
    )
    return (
        f"Chapter: {chapter}\n"
        f"Concept: {concept.name} (NEET PYQ importance weight: {concept.pyq_weight}/5.0)\n"
        f"Generate exactly {len(difficulty_targets)} questions, all on this concept, with these "
        f"(difficulty, question_type) targets in order: {targets}"
    )


def _is_near_duplicate(stem: str, existing_stems: list[str]) -> bool:
    normalized = stem.strip().lower()
    for other in existing_stems:
        other_norm = other.strip().lower()
        if normalized == other_norm:
            return True
        shorter, longer = sorted([normalized, other_norm], key=len)
        if shorter and shorter in longer and len(shorter) > 30:
            return True
    return False


def generate_batch(
    subject: str,
    chapter: str,
    concept: ConceptSpec,
    difficulty_targets: list[int],
    question_types: list[str],
    existing_stems: list[str] | None = None,
) -> list[QuestionSchema]:
    existing_stems = existing_stems or []
    system_prompt = _build_system_prompt(subject)
    user_prompt = _build_user_prompt(chapter, concept, difficulty_targets, question_types)

    draft_batch = call_structured(system_prompt, user_prompt, QuestionDraftBatch)

    valid: list[QuestionSchema] = []
    for draft, difficulty, qtype in zip(draft_batch.questions, difficulty_targets, question_types):
        if _is_near_duplicate(draft.stem, existing_stems):
            logger.warning("Generator produced a near-duplicate stem, discarding: %.80s", draft.stem)
            continue
        if qtype == "diagram" and not draft.diagram_svg:
            logger.warning("Generator produced diagram question with no SVG, discarding: %.80s", draft.stem)
            continue
        try:
            q = QuestionSchema(
                subject=subject,
                chapter=chapter,
                concept=concept.name,
                question_type=qtype,
                difficulty=difficulty,
                bloom_level=max(1, min(5, draft.bloom_level)),
                dok_level=max(1, min(3, draft.dok_level)),
                stem=draft.stem,
                options=draft.options,
                correct_option=draft.correct_option,
                distractor_rationale=draft.distractor_rationale,
                pyq_similarity_note=draft.pyq_similarity_note,
                solution_steps=draft.solution_steps,
                diagram_svg=draft.diagram_svg,
            )
        except Exception:
            logger.exception("Failed to assemble QuestionSchema from draft, discarding")
            continue
        valid.append(q)
        existing_stems.append(q.stem)
    return valid


def generate_single_question(
    subject: str, chapter: str, concept: ConceptSpec, difficulty: int, question_type: str
) -> QuestionSchema:
    results = generate_batch(subject, chapter, concept, [difficulty], [question_type])
    if not results:
        raise ValueError(f"Generator failed to produce a valid question for {concept.name}")
    return results[0]


def generate_pool(
    subject: str,
    chapter: str,
    concepts: list[ConceptSpec],
    questions_per_concept: int | None = None,
) -> list[QuestionSchema]:
    questions_per_concept = questions_per_concept or config.POOL_QUESTIONS_PER_CONCEPT
    all_questions: list[QuestionSchema] = []
    all_stems: list[str] = []

    for concept in concepts:
        difficulty_targets = [_DIFFICULTY_CYCLE[i % len(_DIFFICULTY_CYCLE)] for i in range(questions_per_concept)]
        question_types = [_TYPE_CYCLE[i % len(_TYPE_CYCLE)] for i in range(questions_per_concept)]

        remaining_d, remaining_t = list(difficulty_targets), list(question_types)
        while remaining_d:
            n = min(config.GENERATOR_BATCH_SIZE, len(remaining_d))
            batch_d, batch_t = remaining_d[:n], remaining_t[:n]
            remaining_d, remaining_t = remaining_d[n:], remaining_t[n:]
            try:
                batch = generate_batch(subject, chapter, concept, batch_d, batch_t, existing_stems=all_stems)
                all_questions.extend(batch)
            except Exception:
                logger.exception("Failed to generate batch for concept %s, skipping batch", concept.name)

    return all_questions
