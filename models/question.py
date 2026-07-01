from typing import Literal

from pydantic import BaseModel, Field, model_validator

import config


class DistractorRationale(BaseModel):
    option_key: Literal["A", "B", "C", "D"]
    is_correct: bool
    misconception_tag: str
    explanation: str


class QuestionSchema(BaseModel):
    subject: Literal["Physics", "Chemistry", "Botany", "Zoology"]
    chapter: str
    concept: str
    question_type: Literal["recall", "exception", "diagram", "numerical", "multi_concept"]
    difficulty: int
    bloom_level: int = Field(ge=1, le=5)
    dok_level: int = Field(ge=1, le=3)
    stem: str
    options: dict[Literal["A", "B", "C", "D"], str]
    correct_option: Literal["A", "B", "C", "D"]
    distractor_rationale: list[DistractorRationale]
    pyq_similarity_note: str
    solution_steps: str = ""
    diagram_svg: str = ""

    @model_validator(mode="after")
    def check_consistency(self) -> "QuestionSchema":
        if not (config.MIN_DIFFICULTY <= self.difficulty <= config.MAX_DIFFICULTY):
            raise ValueError(
                f"difficulty must be between {config.MIN_DIFFICULTY} and {config.MAX_DIFFICULTY}"
            )
        keys = {r.option_key for r in self.distractor_rationale}
        if keys != {"A", "B", "C", "D"}:
            raise ValueError("distractor_rationale must cover exactly options A, B, C, D")
        correct_entries = [r for r in self.distractor_rationale if r.is_correct]
        if len(correct_entries) != 1:
            raise ValueError("exactly one distractor_rationale entry must have is_correct=True")
        if correct_entries[0].option_key != self.correct_option:
            raise ValueError("the is_correct rationale entry must match correct_option")
        if set(self.options.keys()) != {"A", "B", "C", "D"}:
            raise ValueError("options must cover exactly A, B, C, D")
        return self


class QuestionBatch(BaseModel):
    questions: list[QuestionSchema]


class QuestionDraft(BaseModel):
    """Lenient LLM-facing schema: only the generative content fields. subject/chapter/concept/
    difficulty/question_type are never trusted from the LLM's restatement - the caller already
    knows them authoritatively (it's what was asked for), so QuestionSchema is built by combining
    this draft's content with the caller's request parameters, not by trusting the model's labels."""

    bloom_level: int = 2  # LLM assigns; 1-5 (Bloom's Revised), default=Understand
    dok_level: int = 1    # LLM assigns; 1-3 (Webb's DOK), default=Recall
    stem: str
    options: dict[Literal["A", "B", "C", "D"], str]
    correct_option: Literal["A", "B", "C", "D"]
    distractor_rationale: list[DistractorRationale]
    pyq_similarity_note: str
    solution_steps: str = ""
    diagram_svg: str = ""

    @model_validator(mode="after")
    def check_consistency(self) -> "QuestionDraft":
        keys = {r.option_key for r in self.distractor_rationale}
        if keys != {"A", "B", "C", "D"}:
            raise ValueError("distractor_rationale must cover exactly options A, B, C, D")
        correct_entries = [r for r in self.distractor_rationale if r.is_correct]
        if len(correct_entries) != 1:
            raise ValueError("exactly one distractor_rationale entry must have is_correct=True")
        if correct_entries[0].option_key != self.correct_option:
            raise ValueError("the is_correct rationale entry must match correct_option")
        if set(self.options.keys()) != {"A", "B", "C", "D"}:
            raise ValueError("options must cover exactly A, B, C, D")
        return self


class QuestionDraftBatch(BaseModel):
    questions: list[QuestionDraft]


class QuestionPublic(BaseModel):
    question_id: str
    subject: str
    chapter: str
    concept: str
    question_type: str
    difficulty: int
    bloom_level: int = 0
    dok_level: int = 0
    stem: str
    options: dict[str, str]
    diagram_svg: str = ""

    @classmethod
    def from_record(cls, record: dict) -> "QuestionPublic":
        return cls(
            question_id=record["question_id"],
            subject=record["subject"],
            chapter=record["chapter"],
            concept=record["concept"],
            question_type=record["question_type"],
            difficulty=record["difficulty"],
            bloom_level=record.get("bloom_level", 0),
            dok_level=record.get("dok_level", 0),
            stem=record["stem"],
            options=record["options"],
            diagram_svg=record.get("diagram_svg", ""),
        )
