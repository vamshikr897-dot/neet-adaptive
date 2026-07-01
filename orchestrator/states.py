from enum import Enum


class SessionStatus(str, Enum):
    GENERATING_POOL = "generating_pool"
    AWAITING_ANSWER = "awaiting_answer"
    EVALUATING = "evaluating"
    ROUTING = "routing"
    COMPLETE = "complete"
    GAP_ANALYSIS = "gap_analysis"
    DONE = "done"
    FAILED = "failed"
