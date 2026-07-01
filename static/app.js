// ─── Subject colour / icon config ────────────────────────────────────────────
const SUBJECT_STYLE = {
    Physics:   { color: "#2563eb", bg: "#eff6ff", icon: "⚛" },
    Chemistry: { color: "#7c3aed", bg: "#f5f3ff", icon: "⚗" },
    Botany:    { color: "#16a34a", bg: "#f0fdf4", icon: "🌿" },
    Zoology:   { color: "#ea580c", bg: "#fff7ed", icon: "🦴" },
};

const DIFFICULTY_COLORS = ["#16a34a", "#65a30d", "#eab308", "#f97316", "#ef4444"];

// ─── App state ────────────────────────────────────────────────────────────────
const state = {
    gradeLevel: "11",
    chapters: [],
    selectedChapter: null,
    selectedConcepts: new Set(),
    sessionId: null,
    currentQuestion: null,
    currentQuestionIndex: null,
    questionStartedAt: null,
};

// ─── Picker DOM refs ──────────────────────────────────────────────────────────
const chapterListEl = document.getElementById("chapter-list");
const startBtn = document.getElementById("start-btn");

// ─── Init ─────────────────────────────────────────────────────────────────────
async function init() {
    // Wire up grade toggle buttons
    document.querySelectorAll(".toggle-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
            document.querySelectorAll(".toggle-btn").forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            state.gradeLevel = btn.dataset.grade;
            state.selectedChapter = null;
            state.selectedConcepts = new Set();
            await loadChapters();
        });
    });

    // Try to recover a saved session
    const savedSession = localStorage.getItem("neet_session_id");
    if (savedSession) {
        try {
            const data = await api.getCurrentQuestion(savedSession);
            if (data.status === "awaiting_answer" && data.question) {
                state.sessionId = savedSession;
                state.currentQuestion = data.question;
                state.currentQuestionIndex = data.question_index;
                showQuizScreen();
                return;
            }
            if (data.status === "complete" || data.status === "done") {
                state.sessionId = savedSession;
                showReportScreen();
                return;
            }
        } catch (_) {
            // Session expired or not found — fall through to picker
        }
        localStorage.removeItem("neet_session_id");
    }

    await loadChapters();
}

// ─── Chapter / concept picker ─────────────────────────────────────────────────
async function loadChapters() {
    chapterListEl.innerHTML = `<div class="loading">Loading chapters…</div>`;
    const { chapters } = await api.getChapters(state.gradeLevel);
    state.chapters = chapters;
    renderChapterList();
}

function renderChapterList() {
    if (state.chapters.length === 0) {
        chapterListEl.innerHTML = `<div class="loading">No chapters found.</div>`;
        updateStartButton();
        return;
    }

    // Group chapters by subject (preserving API order within each group)
    const groups = {};
    state.chapters.forEach((ch, idx) => {
        if (!groups[ch.subject]) groups[ch.subject] = [];
        groups[ch.subject].push({ ch, idx });
    });

    chapterListEl.innerHTML = Object.entries(groups).map(([subject, items]) => {
        const s = SUBJECT_STYLE[subject] || { color: "#2c5f9e", bg: "#eff6ff", icon: "📚" };
        const cards = items.map(({ ch, idx }) => {
            const isSelected = state.selectedChapter === idx;
            const chipsHtml = isSelected
                ? `<div class="concept-chips">${ch.concepts.map((c) => {
                    const excluded = !state.selectedConcepts.has(c.name);
                    return `<span class="concept-chip${excluded ? " excluded" : ""}"
                        data-chapter="${idx}" data-concept="${escapeAttr(c.name)}">${escapeHtml(c.name)}</span>`;
                }).join("")}</div>`
                : "";
            return `
                <div class="chapter-card${isSelected ? " selected" : ""}" data-chapter="${idx}"
                     style="--subject-color:${s.color};--subject-bg:${s.bg}">
                    <div class="chapter-card-header">
                        <span class="chapter-card-name">${escapeHtml(ch.chapter)}</span>
                        <span class="chapter-grade-pill">Gr ${escapeHtml(ch.grade_level || state.gradeLevel)}</span>
                    </div>
                    ${chipsHtml}
                </div>`;
        }).join("");

        return `
            <div class="subject-group">
                <div class="subject-group-header" style="color:${s.color}">
                    <span class="subject-icon">${s.icon}</span>
                    <span>${escapeHtml(subject)}</span>
                </div>
                ${cards}
            </div>`;
    }).join("");

    // Chapter click
    chapterListEl.querySelectorAll(".chapter-card").forEach((el) => {
        el.addEventListener("click", (e) => {
            if (e.target.classList.contains("concept-chip")) return;
            selectChapter(Number(el.dataset.chapter));
        });
    });

    // Concept chip click
    chapterListEl.querySelectorAll(".concept-chip").forEach((el) => {
        el.addEventListener("click", (e) => {
            e.stopPropagation();
            const idx = Number(el.dataset.chapter);
            if (state.selectedChapter !== idx) selectChapter(idx);
            else toggleConcept(el.dataset.concept);
        });
    });

    // Concept hint
    const hint = document.getElementById("concept-hint");
    hint.classList.toggle("hidden", state.selectedChapter === null);

    updateStartButton();
}

function selectChapter(idx) {
    state.selectedChapter = idx;
    state.selectedConcepts = new Set(state.chapters[idx].concepts.map((c) => c.name));
    renderChapterList();
}

function toggleConcept(conceptName) {
    if (state.selectedConcepts.has(conceptName)) {
        state.selectedConcepts.delete(conceptName);
    } else {
        state.selectedConcepts.add(conceptName);
    }
    renderChapterList();
}

function updateStartButton() {
    const hasSelection = state.selectedChapter !== null && state.selectedConcepts.size > 0;
    startBtn.disabled = !hasSelection;
}

startBtn.addEventListener("click", startAssessment);

async function startAssessment() {
    const chapter = state.chapters[state.selectedChapter];
    const allConceptsSelected = state.selectedConcepts.size === chapter.concepts.length;

    startBtn.disabled = true;
    startBtn.textContent = "Generating first question…";

    try {
        const payload = {
            grade_level: state.gradeLevel,
            subject: chapter.subject,
            chapter: chapter.chapter,
            selected_concepts: allConceptsSelected ? [] : Array.from(state.selectedConcepts),
        };
        const result = await api.startSession(payload);
        state.sessionId = result.session_id;
        state.currentQuestion = result.question;
        state.currentQuestionIndex = result.question_index;
        localStorage.setItem("neet_session_id", result.session_id);
        showQuizScreen();
    } catch (err) {
        alert(`Could not start assessment: ${err.message}`);
        startBtn.disabled = false;
        startBtn.textContent = "Start Assessment";
    }
}

// ─── Utilities ────────────────────────────────────────────────────────────────
function escapeHtml(s) {
    if (s == null) return "";
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function escapeAttr(s) {
    return escapeHtml(s).replace(/"/g, "&quot;");
}

function renderMath(el) {
    if (typeof renderMathInElement === "function") {
        renderMathInElement(el, {
            delimiters: [
                { left: "$$", right: "$$", display: true },
                { left: "$", right: "$", display: false },
                { left: "\\(", right: "\\)", display: false },
                { left: "\\[", right: "\\]", display: true },
            ],
            throwOnError: false,
        });
    }
}

function renderDifficultyDots(difficulty) {
    return `<div class="difficulty-dots" title="Difficulty ${difficulty}/5">${
        [1, 2, 3, 4, 5].map((i) =>
            `<span class="diff-dot${i <= difficulty ? " filled" : ""}"${
                i <= difficulty ? ` style="background:${DIFFICULTY_COLORS[i - 1]}"` : ""
            }></span>`
        ).join("")
    }</div>`;
}

// ─── Quiz screen ──────────────────────────────────────────────────────────────
function showQuizScreen() {
    document.getElementById("picker-screen").classList.add("hidden");
    document.getElementById("quiz-screen").classList.remove("hidden");
    state.questionStartedAt = Date.now();
    renderQuestion();
}

const questionCounterEl = document.getElementById("question-counter");
const questionTimerEl = document.getElementById("question-timer");
const nextBtnTopEl = document.getElementById("next-btn-top");
const questionCardEl = document.getElementById("question-card");

document.getElementById("reset-btn").addEventListener("click", () => {
    if (!confirm("Start over? Your current session progress will be lost.")) return;
    stopTimer();
    localStorage.removeItem("neet_session_id");
    state.sessionId = null;
    state.currentQuestion = null;
    state.currentQuestionIndex = null;
    document.getElementById("quiz-screen").classList.add("hidden");
    document.getElementById("report-screen").classList.add("hidden");
    document.getElementById("picker-screen").classList.remove("hidden");
    startBtn.disabled = false;
    startBtn.textContent = "Start Assessment";
    loadChapters();
});

let timerInterval = null;

function startTimer() {
    if (timerInterval) clearInterval(timerInterval);
    timerInterval = setInterval(() => {
        const elapsed = Math.floor((Date.now() - state.questionStartedAt) / 1000);
        questionTimerEl.textContent = `⏱ ${elapsed}s`;
    }, 500);
}

function stopTimer() {
    if (timerInterval) clearInterval(timerInterval);
}

function advanceToNext(result) {
    nextBtnTopEl.classList.add("hidden");
    questionTimerEl.style.visibility = "";
    if (result.status === "complete") {
        showReportScreen();
    } else {
        state.currentQuestion = result.next_question;
        state.currentQuestionIndex = result.question_index;
        state.questionStartedAt = Date.now();
        renderQuestion();
    }
}

function renderQuestion() {
    const q = state.currentQuestion;
    questionCounterEl.textContent = `Question ${state.currentQuestionIndex || 1}`;
    nextBtnTopEl.classList.add("hidden");
    questionTimerEl.style.visibility = "";
    startTimer();

    const s = SUBJECT_STYLE[q.subject] || { color: "#2c5f9e", bg: "#eff6ff", icon: "📚" };
    questionCardEl.style.setProperty("--card-accent", s.color);

    const optionsHtml = Object.entries(q.options).map(([key, text]) => `
        <div class="option-item" data-key="${key}">
            <span class="option-key">${key}</span>
            <span>${escapeHtml(text)}</span>
        </div>`).join("");

    const diagramHtml = q.diagram_svg
        ? `<img class="question-diagram"
               src="data:image/svg+xml;charset=utf-8,${encodeURIComponent(q.diagram_svg)}"
               alt="Question diagram" />`
        : "";

    const typeLabel = q.question_type.replace(/_/g, " ");

    questionCardEl.innerHTML = `
        <div class="question-meta">
            <div class="meta-left">
                <span class="meta-subject-pill" style="background:${s.bg};color:${s.color}">${s.icon} ${escapeHtml(q.subject)}</span>
                <span class="meta-concept">${escapeHtml(q.concept)}</span>
            </div>
            <div class="meta-right">
                <span class="meta-type-pill">${escapeHtml(typeLabel)}</span>
                ${renderDifficultyDots(q.difficulty)}
            </div>
        </div>
        ${diagramHtml}
        <div class="question-stem">${escapeHtml(q.stem)}</div>
        <div class="option-list">${optionsHtml}</div>
        <div id="feedback-area"></div>
    `;

    questionCardEl.dataset.answered = "false";
    questionCardEl.querySelectorAll(".option-item").forEach((el) => {
        el.addEventListener("click", () => selectOption(el.dataset.key));
    });
    renderMath(questionCardEl);
}

function selectOption(key) {
    if (questionCardEl.dataset.answered === "true") return;
    questionCardEl.dataset.answered = "true";
    stopTimer();

    questionCardEl.querySelectorAll(".option-item").forEach((el) => {
        el.classList.toggle("selected", el.dataset.key === key);
    });

    const timeTakenSeconds = (Date.now() - state.questionStartedAt) / 1000;
    submitAnswer(key, timeTakenSeconds);
}

async function submitAnswer(selectedOption, timeTakenSeconds) {
    const feedbackArea = document.getElementById("feedback-area");
    questionTimerEl.style.visibility = "hidden";
    feedbackArea.innerHTML = `
        <div class="eval-loading">
            <span class="eval-spinner"></span>
            <span>Evaluating your answer…</span>
        </div>`;
    try {
        const result = await api.submitAnswer(state.sessionId, {
            selected_option: selectedOption,
            time_taken_seconds: timeTakenSeconds,
        });
        showAnswerFeedback(selectedOption, result);
    } catch (err) {
        feedbackArea.innerHTML = `
            <div class="error-box">
                <span>Could not submit — ${escapeHtml(err.message)}</span>
                <button class="retry-btn" id="retry-submit-btn">Retry</button>
            </div>`;
        document.getElementById("retry-submit-btn").addEventListener("click", () => {
            submitAnswer(selectedOption, timeTakenSeconds);
        });
    }
}

function showAnswerFeedback(selectedOption, result) {
    // Highlight options
    questionCardEl.querySelectorAll(".option-item").forEach((el) => {
        if (el.dataset.key === result.correct_option) {
            el.classList.add("correct");
        } else if (el.dataset.key === selectedOption && !result.correct) {
            el.classList.add("incorrect");
        }
    });

    // Build distractor rationale lookup
    const rationaleMap = {};
    if (Array.isArray(result.distractor_rationale)) {
        result.distractor_rationale.forEach((r) => { rationaleMap[r.option_key] = r; });
    }

    let explanationHtml = "";

    if (!result.correct) {
        // Why the chosen option was wrong
        const wrongText = rationaleMap[selectedOption]?.explanation
            || result.reasoning
            || "This option is incorrect.";
        explanationHtml += `
            <div class="explanation-section">
                <div class="explanation-label">Why option ${escapeHtml(selectedOption)} was wrong</div>
                <p class="explanation-text">${escapeHtml(wrongText)}</p>
            </div>`;

        // Evaluator analysis (LLM reasoning for failure mode) — only for wrong answers
        if (result.reasoning && result.reasoning !== wrongText) {
            explanationHtml += `
                <div class="explanation-section">
                    <div class="explanation-label">Analysis</div>
                    <p class="explanation-text">${escapeHtml(result.reasoning)}</p>
                </div>`;
        }
    }

    // Why the correct option is right — always shown
    const correctText = rationaleMap[result.correct_option]?.explanation
        || "This is the correct answer.";
    explanationHtml += `
        <div class="explanation-section">
            <div class="explanation-label">Why ${escapeHtml(result.correct_option)} is correct</div>
            <p class="explanation-text">${escapeHtml(correctText)}</p>
        </div>`;

    // Solution steps — always shown if present
    if (result.solution_steps) {
        explanationHtml += `
            <div class="explanation-section">
                <div class="explanation-label">Solution</div>
                <div class="solution-steps">${escapeHtml(result.solution_steps)}</div>
            </div>`;
    }

    const verdictClass = result.correct ? "verdict-correct" : "verdict-incorrect";
    const verdictText = result.correct ? "✓ Correct!" : "✗ Incorrect";

    const feedbackArea = document.getElementById("feedback-area");
    feedbackArea.innerHTML = `
        <div class="feedback-box ${verdictClass}">
            <div class="feedback-verdict">${verdictText}</div>
            ${explanationHtml}
        </div>
    `;
    renderMath(feedbackArea);

    // Show top-right Next button
    nextBtnTopEl.textContent = result.status === "complete" ? "View Report →" : "Next →";
    nextBtnTopEl.classList.remove("hidden");
    nextBtnTopEl.onclick = () => advanceToNext(result);
}

// ─── Report screen ────────────────────────────────────────────────────────────
function showReportScreen() {
    document.getElementById("quiz-screen").classList.add("hidden");
    document.getElementById("report-screen").classList.remove("hidden");
    const reportCard = document.getElementById("report-card");
    reportCard.innerHTML = `<div class="loading">Analysing your performance…</div>`;
    loadReport();
}

async function loadReport() {
    const reportCard = document.getElementById("report-card");
    try {
        const report = await api.generateReport(state.sessionId);
        renderReport(report);
    } catch (err) {
        reportCard.innerHTML = `<div class="loading">Could not load report: ${escapeHtml(err.message)}</div>`;
    }
}

function fmtPct(value, digits = 0) {
    return value === null || value === undefined ? "N/A" : `${value.toFixed(digits)}%`;
}

function scoreBadgeClass(scorePct) {
    if (scorePct === null || scorePct === undefined) return "not_assessed";
    if (scorePct >= 75) return "strong";
    if (scorePct < 50) return "weak";
    return "needs_improvement";
}

function renderNeetScoreCard(neetScore) {
    const badgeClass = scoreBadgeClass(neetScore.score_percentage);
    return `
        <div class="verdict-card">
            <div class="chapter-title">
                <span>NEET Score</span>
                <span class="verdict-badge verdict-${badgeClass}">${neetScore.raw_score}/${neetScore.max_score_from_attempted}</span>
            </div>
            <p>${fmtPct(neetScore.score_percentage)} — ${neetScore.correct_count} correct, ${neetScore.incorrect_attempted_count} incorrect, ${neetScore.questions_unattempted} unattempted</p>
            ${neetScore.marks_lost_to_negative_marking > 0
                ? `<p>Negative marking cost you ${neetScore.marks_lost_to_negative_marking} mark(s).</p>`
                : ""}
        </div>`;
}

function renderConceptCard(v) {
    const masteryWidth = v.mastery_pct ?? 0;
    const lowConfidenceNote = v.low_confidence
        ? ` (based on only ${v.questions_asked} questions — treat with caution)`
        : "";
    return `
        <div class="verdict-card">
            <div class="chapter-title">
                <span>${escapeHtml(v.concept)}</span>
                <span class="verdict-badge verdict-${v.verdict}">${v.verdict.replace(/_/g, " ")}</span>
            </div>
            <div class="mastery-bar-track"><div class="mastery-bar-fill ${v.verdict}" style="width:${masteryWidth}%"></div></div>
            <p>${v.mastery_pct !== null ? v.mastery_pct.toFixed(0) + "% mastery" : "Not enough data"}${lowConfidenceNote} — ${v.correct}/${v.questions_asked} correct</p>
            <p>${escapeHtml(v.reasoning)}</p>
        </div>`;
}

function renderLevelTable(title, entries) {
    if (!entries.length) return "";
    const rows = entries.map((l) => `
        <tr><td>${l.level}</td><td>${l.attempted}</td><td>${l.correct}</td><td>${fmtPct(l.accuracy_pct)}</td></tr>
    `).join("");
    return `
        <h4>${title}</h4>
        <table class="level-breakdown-table">
            <thead><tr><th>Level</th><th>Attempted</th><th>Correct</th><th>Accuracy</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
}

function renderErrorAnalysisCard(errorAnalysis) {
    if (errorAnalysis.total_incorrect_attempted === 0) {
        return `
            <div class="verdict-card">
                <div class="chapter-title"><span>Error Analysis</span></div>
                <p>No incorrect attempted answers — nothing to analyse.</p>
            </div>`;
    }
    return `
        <div class="verdict-card">
            <div class="chapter-title"><span>Error Analysis</span></div>
            <p>Conceptual gaps: ${errorAnalysis.conceptual_gap_count} (${fmtPct(errorAnalysis.conceptual_gap_pct)})</p>
            <p>Calculation errors: ${errorAnalysis.calculation_error_count} (${fmtPct(errorAnalysis.calculation_error_pct)})</p>
            <p>Missed exceptions/edge cases: ${errorAnalysis.exception_not_known_count} (${fmtPct(errorAnalysis.exception_not_known_pct)})</p>
        </div>`;
}

function tradeoffMessage(tag) {
    switch (tag) {
        case "rushing_costs_accuracy":
            return "You answer faster-than-expected questions noticeably less accurately — slowing down may help.";
        case "overthinking_without_gain":
            return "Taking extra time isn't converting into higher accuracy — trust your first read more.";
        case "well_balanced":
            return "Your speed and accuracy are well balanced.";
        default:
            return "Not enough questions in one speed bucket yet to compare.";
    }
}

function renderTimeEfficiencyCard(timeEfficiency) {
    if (timeEfficiency.avg_actual_seconds === null) {
        return `
            <div class="verdict-card">
                <div class="chapter-title"><span>Time Efficiency</span></div>
                <p>No attempted questions to analyse.</p>
            </div>`;
    }
    return `
        <div class="verdict-card">
            <div class="chapter-title"><span>Time Efficiency</span></div>
            <p>You averaged ${timeEfficiency.avg_actual_seconds.toFixed(0)}s vs an estimated ${timeEfficiency.avg_expected_seconds.toFixed(0)}s per question (${timeEfficiency.efficiency_ratio.toFixed(2)}x expected).</p>
            <p>Hesitation index: ${fmtPct(timeEfficiency.hesitation_index)} of attempted questions were answered correctly but took over 1.5x the expected time — a possible sign of overthinking rather than not knowing the material.</p>
            <p>${tradeoffMessage(timeEfficiency.tradeoff_tag)}</p>
            <p class="caveat-note">${escapeHtml(timeEfficiency.heuristic_note)}</p>
        </div>`;
}

function renderRecoveryCard(recovery) {
    const recoveryLine = recovery.recovery_rate !== null
        ? `After an incorrect answer, you bounced back ${fmtPct(recovery.recovery_rate)} of the time.`
        : "You didn't have any incorrect answers to recover from — great consistency.";
    const progressionLine = recovery.progression_available
        ? `First half: ${fmtPct(recovery.first_half_accuracy_pct)} accuracy (avg difficulty ${recovery.first_half_avg_difficulty.toFixed(1)}) → Second half: ${fmtPct(recovery.second_half_accuracy_pct)} (avg difficulty ${recovery.second_half_avg_difficulty.toFixed(1)}).`
        : "Session too short to show progression.";
    return `
        <div class="verdict-card">
            <div class="chapter-title"><span>Recovery &amp; Progression</span></div>
            <p>${recoveryLine}</p>
            <p>${progressionLine}</p>
        </div>`;
}

function renderPriorityConcepts(priorityConcepts) {
    if (!priorityConcepts.length) {
        return `<h3>Fix These First</h3><p>No high-priority gaps detected — nice work.</p>`;
    }
    const cards = priorityConcepts.map((p) => `
        <div class="verdict-card">
            <div class="chapter-title">
                <span>${escapeHtml(p.concept)}</span>
                <span class="verdict-badge verdict-${p.verdict}">${p.verdict.replace(/_/g, " ")}</span>
            </div>
            <p>Appears frequently in NEET PYQs (weight ${p.pyq_weight.toFixed(1)}) — ${p.mastery_pct !== null ? p.mastery_pct.toFixed(0) + "% mastery" : "not enough data"}</p>
        </div>`).join("");
    return `<h3>Fix These First (highest exam impact)</h3>${cards}`;
}

function renderReport(report) {
    const reportCard = document.getElementById("report-card");
    const verdictCards = report.concept_verdicts.map(renderConceptCard).join("");
    const levelTables = renderLevelTable("Bloom's Taxonomy", report.bloom_dok_breakdown.bloom)
        + renderLevelTable("Webb's DOK", report.bloom_dok_breakdown.dok);

    reportCard.innerHTML = `
        <p>${escapeHtml(report.summary)}</p>
        ${renderNeetScoreCard(report.neet_score)}
        <h3>Concept Breakdown</h3>
        ${verdictCards}
        ${levelTables ? `<h3>Cognitive Level Breakdown</h3>${levelTables}` : ""}
        ${renderErrorAnalysisCard(report.error_analysis)}
        ${renderTimeEfficiencyCard(report.time_efficiency)}
        ${renderRecoveryCard(report.recovery_progression)}
        ${renderPriorityConcepts(report.priority_concepts)}
        <button class="primary-btn" style="margin-top:20px;" onclick="
            localStorage.removeItem('neet_session_id');
            location.reload();
        ">Start New Session</button>
    `;
}

// ─── Boot ─────────────────────────────────────────────────────────────────────
init();
