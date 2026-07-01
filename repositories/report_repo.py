import json

import db
from models.report import (
    BloomDokBreakdown,
    ConceptVerdict,
    ErrorAnalysis,
    GapReport,
    NeetScore,
    PriorityConcept,
    RecoveryProgression,
    TimeEfficiency,
)


def insert(report: GapReport) -> None:
    insights = {
        "neet_score": report.neet_score.model_dump(),
        "bloom_dok_breakdown": report.bloom_dok_breakdown.model_dump(),
        "error_analysis": report.error_analysis.model_dump(),
        "time_efficiency": report.time_efficiency.model_dump(),
        "recovery_progression": report.recovery_progression.model_dump(),
        "priority_concepts": [p.model_dump() for p in report.priority_concepts],
    }
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO gap_reports (
                session_id, overall_score, ability_estimate_final,
                concept_verdicts_json, summary, generated_at, insights_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.session_id,
                report.overall_score,
                report.ability_estimate_final,
                json.dumps([v.model_dump() for v in report.concept_verdicts]),
                report.summary,
                report.generated_at,
                json.dumps(insights),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get(session_id: str) -> GapReport | None:
    conn = db.get_connection()
    try:
        row = conn.execute(
            """
            SELECT gr.*, s.chapter FROM gap_reports gr
            JOIN sessions s ON s.session_id = gr.session_id
            WHERE gr.session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            insights = json.loads(row["insights_json"])
            verdicts = [ConceptVerdict(**v) for v in json.loads(row["concept_verdicts_json"])]
            return GapReport(
                session_id=row["session_id"],
                chapter=row["chapter"],
                overall_score=row["overall_score"],
                ability_estimate_final=row["ability_estimate_final"],
                concept_verdicts=verdicts,
                neet_score=NeetScore(**insights["neet_score"]),
                bloom_dok_breakdown=BloomDokBreakdown(**insights["bloom_dok_breakdown"]),
                error_analysis=ErrorAnalysis(**insights["error_analysis"]),
                time_efficiency=TimeEfficiency(**insights["time_efficiency"]),
                recovery_progression=RecoveryProgression(**insights["recovery_progression"]),
                priority_concepts=[PriorityConcept(**p) for p in insights["priority_concepts"]],
                summary=row["summary"],
                generated_at=row["generated_at"],
            )
        except (KeyError, TypeError, ValueError):
            # Pre-existing report from before the insights_json column was added - treat as
            # missing so the caller regenerates it with the current report shape.
            return None
    finally:
        conn.close()
