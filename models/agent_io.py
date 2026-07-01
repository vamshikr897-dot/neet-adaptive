from typing import Literal

from pydantic import BaseModel

from models.question import QuestionSchema


class ConceptSpec(BaseModel):
    name: str
    pyq_weight: float


class GeneratorRequest(BaseModel):
    subject: str
    chapter: str
    concepts: list[ConceptSpec]
    difficulty_targets: list[int]
    batch_size: int = 3


class QuestionSpec(BaseModel):
    concept: str
    question_type: Literal["recall", "exception", "diagram", "numerical", "multi_concept"]
    target_difficulty: int


class EvaluatorLLMResult(BaseModel):
    failure_mode: Literal["conceptual_gap", "calculation_error", "exception_not_known"]
    reasoning: str


class EvaluatorResult(BaseModel):
    correct: bool
    failure_mode: Literal["conceptual_gap", "calculation_error", "exception_not_known", "none"]
    reasoning: str


class ConceptNarration(BaseModel):
    concept: str
    reasoning: str


class GapAnalyserLLMResult(BaseModel):
    concept_narrations: list[ConceptNarration]
    summary: str
