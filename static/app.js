// ─── Subject colour / icon config ────────────────────────────────────────────
const SUBJECT_STYLE = {
    Physics:   { color: "#2563eb", bg: "#eff6ff", icon: "⚛️" },
    Chemistry: { color: "#7c3aed", bg: "#f5f3ff", icon: "⚗️" },
    Botany:    { color: "#16a34a", bg: "#f0fdf4", icon: "🌿" },
    Zoology:   { color: "#ea580c", bg: "#fff7ed", icon: "🦴" },
};

const DIFFICULTY_COLORS = ["#16a34a", "#65a30d", "#eab308", "#f97316", "#ef4444"];

// Mirrors config.py's NEET_CORRECT_MARKS / NEET_INCORRECT_MARKS - not exposed via the
// GapReport JSON, so duplicated here for display purposes only.
const NEET_MARKS = { correct: 4, incorrect: -1 };

// Canonical wording reused verbatim from agents/generator.py's system prompt.
const BLOOM_LABELS = { 1: "Remember", 2: "Understand", 3: "Apply", 4: "Analyze", 5: "Evaluate" };
const DOK_LABELS = { 1: "Recall & Reproduction", 2: "Skills & Concepts", 3: "Strategic Thinking" };

// Matches static/style.css's body font-family so Chart.js text doesn't visually diverge.
// NOTE: chart.umd.min.js loads via <script defer>, which (per HTML spec) executes AFTER
// this non-deferred script even though its <script> tag appears earlier in the document -
// so `Chart` is not yet defined at top-level here. The actual Chart.defaults assignment
// happens in renderReport() instead, right before any chart is constructed.
const CHART_FONT_FAMILY = '-apple-system, "Segoe UI", Roboto, sans-serif';

// ─── App state ────────────────────────────────────────────────────────────────
const state = {
    gradeLevel: "11",
    subject: Object.keys(SUBJECT_STYLE)[0],
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
const subjectSelectEl = document.getElementById("subject-select");
const pickerScreenEl = document.getElementById("picker-screen");

function applySubjectTheme(subject) {
    const s = SUBJECT_STYLE[subject] || { color: "#2c5f9e", bg: "#eff6ff" };
    pickerScreenEl.style.setProperty("--subject-color", s.color);
    pickerScreenEl.style.setProperty("--subject-bg", s.bg);
}

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

    // Populate + wire up the subject dropdown
    subjectSelectEl.innerHTML = Object.entries(SUBJECT_STYLE)
        .map(([subject, s]) => `<option value="${escapeAttr(subject)}" style="color:${s.color}">${s.icon} ${escapeHtml(subject)}</option>`)
        .join("");
    subjectSelectEl.value = state.subject;
    applySubjectTheme(state.subject);
    subjectSelectEl.addEventListener("change", async () => {
        state.subject = subjectSelectEl.value;
        state.selectedChapter = null;
        state.selectedConcepts = new Set();
        applySubjectTheme(state.subject);
        await loadChapters();
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
    const { chapters } = await api.getChapters(state.gradeLevel, state.subject);
    state.chapters = chapters;
    renderChapterList();
}

function renderChapterList() {
    if (state.chapters.length === 0) {
        chapterListEl.innerHTML = `<div class="loading">No chapters found.</div>`;
        updateStartButton();
        return;
    }

    const s = SUBJECT_STYLE[state.subject] || { color: "#2c5f9e", bg: "#eff6ff", icon: "📚" };

    chapterListEl.innerHTML = state.chapters.map((ch, idx) => {
        const isSelected = state.selectedChapter === idx;
        const total = ch.concepts.length;
        const countPill = isSelected
            ? `${state.selectedConcepts.size}/${total} selected`
            : `${total} concept${total === 1 ? "" : "s"}`;
        const chipsHtml = isSelected
            ? `
                <p class="concept-hint">All concepts included by default — tap a concept to exclude it.</p>
                <div class="concept-chips">${ch.concepts.map((c) => {
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
                    <span class="concept-count-pill">${countPill}</span>
                </div>
                ${chipsHtml}
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
const quizSessionMetaEl = document.getElementById("quiz-session-meta");

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

    quizSessionMetaEl.innerHTML = `
        <span class="meta-subject-pill" style="background:${s.bg};color:${s.color}">${s.icon} ${escapeHtml(q.subject)}</span>
        <span class="meta-chapter-tag" style="border-color:${s.color};color:${s.color}">${escapeHtml(q.chapter)}</span>
    `;

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
const REPORT_LOADING_MESSAGES = [
    "Calculating your NEET score…",
    "Assessing concept mastery…",
    "Analyzing error patterns…",
    "Reviewing time efficiency…",
    "Identifying priority concepts…",
    "Finalizing your report…",
];

function showReportScreen() {
    document.getElementById("picker-screen").classList.add("hidden");
    document.getElementById("quiz-screen").classList.add("hidden");
    document.getElementById("report-screen").classList.remove("hidden");
    const reportCard = document.getElementById("report-card");
    reportCard.innerHTML = `
        <div class="report-loading">
            <span class="report-loading-spinner"></span>
            <p class="report-loading-text">${REPORT_LOADING_MESSAGES[0]}</p>
        </div>`;
    let i = 0;
    const messageEl = reportCard.querySelector(".report-loading-text");
    const intervalId = setInterval(() => {
        i = (i + 1) % REPORT_LOADING_MESSAGES.length;
        if (messageEl.isConnected) messageEl.textContent = REPORT_LOADING_MESSAGES[i];
    }, 2000);
    loadReport(intervalId);
}

async function loadReport(intervalId) {
    const reportCard = document.getElementById("report-card");
    try {
        const report = await api.generateReport(state.sessionId);
        renderReport(report);
    } catch (err) {
        reportCard.innerHTML = `<div class="loading">Could not load report: ${escapeHtml(err.message)}</div>`;
    } finally {
        clearInterval(intervalId);
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

// ─── Dashboard chart helpers ────────────────────────────────────────────────
let _verdictColorsCache = null;
function getVerdictColors() {
    if (_verdictColorsCache) return _verdictColorsCache;
    const style = getComputedStyle(document.documentElement);
    const read = (name, fallback) => (style.getPropertyValue(name) || "").trim() || fallback;
    _verdictColorsCache = {
        strong: read("--color-correct", "#1f9d55"),
        weak: read("--color-wrong", "#d64545"),
        needs_improvement: read("--color-warning", "#e6a23c"),
        not_assessed: read("--color-muted", "#6b7280"),
        primary: read("--color-primary", "#2c5f9e"),
        text: read("--color-text", "#1f2430"),
    };
    return _verdictColorsCache;
}

function truncateLabel(text, maxLen = 24) {
    return text.length > maxLen ? `${text.slice(0, maxLen - 1)}…` : text;
}

function accuracyColor(pct) {
    const colors = getVerdictColors();
    if (pct >= 75) return colors.strong;
    if (pct < 50) return colors.weak;
    return colors.needs_improvement;
}

function wrapTooltipText(text, maxLen = 42) {
    const words = text.split(" ");
    const lines = [];
    let current = "";
    for (const word of words) {
        if ((current + " " + word).trim().length > maxLen) {
            lines.push(current.trim());
            current = word;
        } else {
            current += " " + word;
        }
    }
    if (current.trim()) lines.push(current.trim());
    return lines;
}

const _donutCenterTextPlugin = {
    id: "donutCenterText",
    afterDraw(chart) {
        const opts = chart.options.plugins && chart.options.plugins.donutCenterText;
        if (!opts) return;
        const { ctx, chartArea: { width, height, left, top } } = chart;
        ctx.save();
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.font = `bold 22px ${CHART_FONT_FAMILY}`;
        ctx.fillStyle = opts.color;
        ctx.fillText(String(opts.value), left + width / 2, top + height / 2 - 8);
        ctx.font = `11px ${CHART_FONT_FAMILY}`;
        ctx.fillStyle = opts.mutedColor;
        ctx.fillText(opts.label, left + width / 2, top + height / 2 + 12);
        ctx.restore();
    },
};

// ─── Hero ────────────────────────────────────────────────────────────────────
function renderHero(neetScore, timeEfficiency, subject, chapter, abilityEstimateFinal) {
    const badgeClass = scoreBadgeClass(neetScore.score_percentage);
    const accuracy = neetScore.questions_attempted > 0
        ? `${((100 * neetScore.correct_count) / neetScore.questions_attempted).toFixed(0)}%`
        : "N/A";
    const avgTime = timeEfficiency.avg_actual_seconds !== null
        ? `${timeEfficiency.avg_actual_seconds.toFixed(0)}s`
        : "N/A";
    const subjectStyle = SUBJECT_STYLE[subject] || { icon: "📚" };
    return `
        <div class="report-hero verdict-${badgeClass}">
            <div class="chart-section-title hero-heading">Overall Summary Report</div>
            <div class="hero-session-meta">${subjectStyle.icon} ${escapeHtml(subject)} · ${escapeHtml(chapter)}</div>
            <div class="hero-metric-row hero-metric-row-primary">
                <div class="hero-metric">
                    <div class="hero-metric-value hero-metric-value-lg">${neetScore.raw_score}/${neetScore.max_score_from_attempted}</div>
                    <div class="hero-metric-label">Score</div>
                </div>
                <div class="hero-metric">
                    <span class="verdict-badge verdict-${badgeClass}">${badgeClass.replace(/_/g, " ")}</span>
                    <div class="hero-metric-label">Overall Performance</div>
                </div>
                <div class="hero-metric">
                    <div class="hero-metric-value">${fmtPct(neetScore.score_percentage)}</div>
                    <div class="hero-metric-label">Percentage</div>
                </div>
            </div>
            <div class="hero-metric-row">
                <div class="hero-metric">
                    <div class="hero-metric-value">${neetScore.questions_attempted}</div>
                    <div class="hero-metric-label">Total Questions</div>
                </div>
                <div class="hero-metric">
                    <div class="hero-metric-value stat-correct">${neetScore.correct_count} (${NEET_MARKS.correct > 0 ? "+" : ""}${NEET_MARKS.correct})</div>
                    <div class="hero-metric-label">Correct</div>
                </div>
                <div class="hero-metric">
                    <div class="hero-metric-value stat-incorrect">${neetScore.incorrect_attempted_count} (${NEET_MARKS.incorrect})</div>
                    <div class="hero-metric-label">Incorrect</div>
                </div>
            </div>
            <div class="hero-metric-row">
                <div class="hero-metric">
                    <div class="hero-metric-value">${accuracy}</div>
                    <div class="hero-metric-label">Overall Accuracy</div>
                </div>
                <div class="hero-metric">
                    <div class="hero-metric-value">${avgTime}</div>
                    <div class="hero-metric-label">Avg. Time Taken</div>
                </div>
                <div class="hero-metric">
                    <div class="hero-metric-value">${abilityEstimateFinal.toFixed(1)}/5</div>
                    <div class="hero-metric-label">Final Difficulty Level</div>
                </div>
            </div>
        </div>`;
}

// ─── Next Steps ───────────────────────────────────────────────────────────────
function renderNextSteps(nextSteps) {
    if (!nextSteps || !nextSteps.length) return "";
    const items = nextSteps.map((step) => `<li>${escapeHtml(step)}</li>`).join("");
    return `
        <div class="next-steps-card">
            <div class="chart-section-title">Next Steps</div>
            <ol class="next-steps-list">${items}</ol>
        </div>`;
}

// ─── Concept Mastery chart ───────────────────────────────────────────────────
function renderConceptMasteryChart(conceptVerdicts) {
    const height = Math.max(180, conceptVerdicts.length * 44);
    const hasLowConfidence = conceptVerdicts.some((v) => v.low_confidence);
    return `
        <div class="chart-section-title">Concept Mastery</div>
        <p class="caveat-note">Mastery is difficulty-weighted accuracy — getting harder questions right counts for more. Strong ≥75%, Weak &lt;50%. Tap a bar for details.</p>
        <div class="concept-chart-scroll">
            <div class="chart-container" style="height:${height}px"><canvas id="concept-mastery-chart"></canvas></div>
        </div>
        ${hasLowConfidence ? '<p class="caveat-note">* Based on fewer than 5 questions — treat with caution.</p>' : ""}`;
}

function initConceptMasteryChart(conceptVerdicts) {
    const canvas = document.getElementById("concept-mastery-chart");
    if (!canvas || !conceptVerdicts.length) return;
    const colors = getVerdictColors();
    const labels = conceptVerdicts.map((v) => {
        const name = truncateLabel(v.concept);
        return v.low_confidence ? `${name} *` : name;
    });
    const data = conceptVerdicts.map((v) => v.mastery_pct ?? 0);
    const backgroundColor = conceptVerdicts.map((v) => colors[v.verdict] || colors.not_assessed);
    new Chart(canvas, {
        type: "bar",
        data: { labels, datasets: [{ data, backgroundColor, minBarLength: 4 }] },
        options: {
            indexAxis: "y",
            responsive: true,
            maintainAspectRatio: false,
            scales: { x: { min: 0, max: 100, ticks: { callback: (v) => v + "%" } } },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        title: (items) => conceptVerdicts[items[0].dataIndex].concept,
                        label: (ctx) => {
                            const v = conceptVerdicts[ctx.dataIndex];
                            const masteryStr = v.mastery_pct !== null ? `${v.mastery_pct.toFixed(0)}% mastery` : "Not enough data";
                            return [masteryStr, `${v.correct}/${v.questions_asked} correct`];
                        },
                        afterLabel: (ctx) => {
                            const v = conceptVerdicts[ctx.dataIndex];
                            return [`Verdict: ${v.verdict.replace(/_/g, " ")}`];
                        },
                    },
                },
            },
        },
    });
}

// ─── Priority Concepts (plain list, not a chart) ─────────────────────────────
function _failureBreakdownText(p) {
    const parts = [];
    if (p.conceptual_gap > 0) parts.push(`${p.conceptual_gap} conceptual gap${p.conceptual_gap > 1 ? "s" : ""}`);
    if (p.calculation_error > 0) parts.push(`${p.calculation_error} calculation error${p.calculation_error > 1 ? "s" : ""}`);
    if (p.exception_not_known > 0) parts.push(`${p.exception_not_known} missed exception${p.exception_not_known > 1 ? "s" : ""}`);
    return parts.join(" · ");
}

function renderPriorityConceptsList(priorityConcepts) {
    if (!priorityConcepts.length) {
        // Empty only means no weak/needs-improvement concept cleared the PYQ-weight bar -
        // NOT that there are no gaps at all, so hide the section rather than imply "nice work".
        return "";
    }
    const rows = priorityConcepts.map((p) => {
        const breakdown = _failureBreakdownText(p);
        return `
        <div class="priority-concept-row">
            <div>
                <div class="priority-concept-name">${escapeHtml(p.concept)}</div>
                <div class="priority-concept-meta">PYQ weight ${p.pyq_weight.toFixed(1)} — ${p.mastery_pct !== null ? p.mastery_pct.toFixed(0) + "% mastery" : "not enough data"}</div>
                ${breakdown ? `<div class="priority-concept-meta">${escapeHtml(breakdown)}</div>` : ""}
                ${p.misconception_note ? `<div class="priority-concept-note">${escapeHtml(p.misconception_note)}</div>` : ""}
            </div>
            <span class="verdict-badge verdict-${p.verdict}">${p.verdict.replace(/_/g, " ")}</span>
        </div>`;
    }).join("");
    return `
        <div class="chart-section-title">Fix These First (highest exam impact)</div>
        <p class="caveat-note">PYQ weight is a 1-5 score showing how often this concept has appeared in NEET previous-year questions — higher means more exam-critical. Concepts below 3.0 aren't shown here even if weak.</p>
        ${rows}`;
}

// ─── Strength Concepts (mirrors Priority Concepts) ───────────────────────────
function renderStrengthConceptsList(strengthConcepts) {
    if (!strengthConcepts.length) return "";
    const rows = strengthConcepts.map((s) => `
        <div class="priority-concept-row">
            <div>
                <div class="priority-concept-name">${escapeHtml(s.concept)}</div>
                <div class="priority-concept-meta">PYQ weight ${s.pyq_weight.toFixed(1)} — ${s.mastery_pct !== null ? s.mastery_pct.toFixed(0) + "% mastery" : "not enough data"}</div>
                ${s.expertise_note ? `<div class="priority-concept-note">${escapeHtml(s.expertise_note)}</div>` : ""}
            </div>
            <span class="verdict-badge verdict-strong">strong</span>
        </div>`).join("");
    return `
        <div class="chart-section-title">Strengths</div>
        <p class="caveat-note">What you've already mastered — worth knowing what's working, not just what isn't.</p>
        ${rows}`;
}

// ─── Cognitive Level Breakdown accordion ─────────────────────────────────────
function renderBloomDokAccordion(bloomDokBreakdown, questionTypeBreakdown) {
    const hasData = bloomDokBreakdown.bloom.length > 0 || bloomDokBreakdown.dok.length > 0
        || questionTypeBreakdown.length > 0;
    const body = hasData ? `
        <div class="chart-section-title">Bloom's Taxonomy</div>
        <div class="chart-container chart-fixed-bloom"><canvas id="bloom-chart"></canvas></div>
        <div class="chart-section-title">Webb's DOK</div>
        <div class="chart-container chart-fixed-dok"><canvas id="dok-chart"></canvas></div>
        <div class="chart-section-title">Question Type</div>
        <div class="chart-container chart-fixed-question-type"><canvas id="question-type-chart"></canvas></div>`
        : `<p>No cognitive-level or question-type data available for this session.</p>`;
    return `
        <details class="report-accordion">
            <summary>Cognitive Level Breakdown <span class="accordion-icon">▾</span></summary>
            <div class="accordion-body">${body}</div>
        </details>`;
}

function _levelBarChart(canvasId, entries, labelBuilder) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !entries.length) return;
    const labels = entries.map(labelBuilder);
    const data = entries.map((e) => e.accuracy_pct);
    const backgroundColor = entries.map((e) => accuracyColor(e.accuracy_pct));
    new Chart(canvas, {
        type: "bar",
        data: { labels, datasets: [{ data, backgroundColor, minBarLength: 4 }] },
        options: {
            indexAxis: "y",
            responsive: true,
            maintainAspectRatio: false,
            scales: { x: { min: 0, max: 100, ticks: { callback: (v) => v + "%" } } },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const e = entries[ctx.dataIndex];
                            return `${e.attempted} attempted, ${e.correct} correct (${e.accuracy_pct.toFixed(0)}%)`;
                        },
                    },
                },
            },
        },
    });
}

function humanizeQuestionType(questionType) {
    return questionType.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function initBloomDokCharts(bloomDokBreakdown, questionTypeBreakdown) {
    // Narrow phones need a shorter cap - Chart.js's y-axis label gutter can clip long
    // category labels from the left on very narrow charts rather than wrapping them.
    const maxLen = window.innerWidth < 480 ? 16 : 24;
    _levelBarChart("bloom-chart", bloomDokBreakdown.bloom, (e) => truncateLabel(`${e.level} — ${BLOOM_LABELS[e.level] || "Unclassified"}`, maxLen));
    _levelBarChart("dok-chart", bloomDokBreakdown.dok, (e) => truncateLabel(`DOK ${e.level} — ${DOK_LABELS[e.level] || "Unclassified"}`, maxLen));
    _levelBarChart("question-type-chart", questionTypeBreakdown, (e) => humanizeQuestionType(e.question_type));
}

// ─── Error Analysis donut accordion ──────────────────────────────────────────
function renderErrorDonutAccordion(errorAnalysis) {
    const body = errorAnalysis.total_incorrect_attempted === 0
        ? `<p>No incorrect attempted answers — nothing to analyse.</p>`
        : `<div class="chart-container chart-fixed-donut"><canvas id="error-donut-chart"></canvas></div>`;
    return `
        <details class="report-accordion">
            <summary>Error Analysis <span class="accordion-icon">▾</span></summary>
            <div class="accordion-body">${body}</div>
        </details>`;
}

function initErrorDonutChart(errorAnalysis) {
    const canvas = document.getElementById("error-donut-chart");
    if (!canvas || errorAnalysis.total_incorrect_attempted === 0) return;
    const colors = getVerdictColors();
    const total = errorAnalysis.total_incorrect_attempted;
    new Chart(canvas, {
        type: "doughnut",
        data: {
            labels: ["Conceptual gap", "Calculation error", "Missed exception"],
            datasets: [{
                data: [
                    errorAnalysis.conceptual_gap_count,
                    errorAnalysis.calculation_error_count,
                    errorAnalysis.exception_not_known_count,
                ],
                backgroundColor: [colors.weak, colors.needs_improvement, colors.not_assessed],
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: "bottom" },
                donutCenterText: { value: total, label: "incorrect", color: colors.text, mutedColor: colors.not_assessed },
                tooltip: {
                    callbacks: {
                        label: (ctx) => `${ctx.label}: ${ctx.parsed} (${((100 * ctx.parsed) / total).toFixed(0)}%)`,
                    },
                },
            },
        },
        plugins: [_donutCenterTextPlugin],
    });
}

// ─── Time Efficiency accordion (scatter, falls back to text for small N) ────
function renderTimeEfficiencyAccordion(timeEfficiency, questionHistory) {
    const attempted = questionHistory.filter((q) => q.attempted);
    const useChart = attempted.length >= 3 && timeEfficiency.avg_actual_seconds !== null;
    let body;
    if (timeEfficiency.avg_actual_seconds === null) {
        body = `<p>No attempted questions to analyse.</p>`;
    } else if (useChart) {
        const height = Math.max(200, attempted.length * 28);
        body = `
            <p class="caveat-note">Each bar is one question, ordered by when it was asked — longer bars took more time.</p>
            <div class="chart-container" style="height:${height}px"><canvas id="time-bar-chart"></canvas></div>`;
    } else {
        body = `
            <p>You averaged ${timeEfficiency.avg_actual_seconds.toFixed(0)}s vs an estimated ${timeEfficiency.avg_expected_seconds.toFixed(0)}s per question (${timeEfficiency.efficiency_ratio.toFixed(2)}x expected).</p>
            <p>Hesitation index: ${fmtPct(timeEfficiency.hesitation_index)} of attempted questions were answered correctly but took over 1.5x the expected time — a possible sign of overthinking rather than not knowing the material.</p>`;
    }
    const byType = timeEfficiency.by_question_type;
    const byTypeBlock = byType && byType.length > 0
        ? `
            <div class="chart-section-title">Avg Time by Question Type</div>
            <div class="chart-container chart-fixed-question-type"><canvas id="time-by-type-chart"></canvas></div>`
        : "";
    const rushedGuessNote = timeEfficiency.rushed_guess_count > 0
        ? `<p class="caveat-note">${timeEfficiency.rushed_guess_count} wrong answer${timeEfficiency.rushed_guess_count > 1 ? "s were" : " was"} given well faster than expected — a possible sign of a rushed guess rather than a genuine attempt.</p>`
        : "";
    return `
        <details class="report-accordion">
            <summary>Time Efficiency <span class="accordion-icon">▾</span></summary>
            <div class="accordion-body">${body}${rushedGuessNote}${byTypeBlock}</div>
        </details>`;
}

function initTimeByTypeChart(timeEfficiency) {
    const canvas = document.getElementById("time-by-type-chart");
    const entries = timeEfficiency.by_question_type;
    if (!canvas || !entries || !entries.length) return;
    const colors = getVerdictColors();
    const labels = entries.map((e) => humanizeQuestionType(e.question_type));
    const data = entries.map((e) => e.avg_actual_seconds);
    const backgroundColor = entries.map((e) => (e.avg_actual_seconds <= e.avg_expected_seconds ? colors.strong : colors.needs_improvement));
    new Chart(canvas, {
        type: "bar",
        data: { labels, datasets: [{ data, backgroundColor, minBarLength: 4 }] },
        options: {
            indexAxis: "y",
            responsive: true,
            maintainAspectRatio: false,
            scales: { x: { title: { display: true, text: "Avg time (seconds)" }, beginAtZero: true } },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const e = entries[ctx.dataIndex];
                            return [
                                `${e.avg_actual_seconds.toFixed(0)}s avg — ${e.count} question${e.count > 1 ? "s" : ""}`,
                                `Expected ~${e.avg_expected_seconds.toFixed(0)}s`,
                            ];
                        },
                    },
                },
            },
        },
    });
}

function initTimeEfficiencyChart(timeEfficiency, questionHistory) {
    const canvas = document.getElementById("time-bar-chart");
    if (!canvas) return;
    const colors = getVerdictColors();
    const attempted = questionHistory.filter((q) => q.attempted).sort((a, b) => a.question_index - b.question_index);
    const labels = attempted.map((q) => `Q${q.question_index}`);
    const data = attempted.map((q) => q.time_taken_seconds);
    const backgroundColor = attempted.map((q) => (q.correct ? colors.strong : colors.weak));
    new Chart(canvas, {
        type: "bar",
        data: { labels, datasets: [{ data, backgroundColor }] },
        options: {
            indexAxis: "y",
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { title: { display: true, text: "Time taken (seconds)" }, beginAtZero: true },
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const q = attempted[ctx.dataIndex];
                            return [
                                `${q.time_taken_seconds.toFixed(0)}s — ${q.correct ? "Correct" : "Incorrect"}`,
                                `Difficulty ${q.difficulty}/5`,
                            ];
                        },
                    },
                },
            },
        },
    });
}

// ─── Recovery & Progression accordion (line chart, falls back to text) ──────
function computeRollingAccuracy(questionHistory) {
    let correct = 0;
    let total = 0;
    return questionHistory.map((q) => {
        total += 1;
        if (q.correct) correct += 1;
        return { question_index: q.question_index, accuracy_pct: (100 * correct) / total, correct: q.correct };
    });
}

function renderRecoveryProgressionAccordion(recoveryProgression, questionHistory) {
    const recoveryLine = recoveryProgression.recovery_rate !== null
        ? `After an incorrect answer, you bounced back ${fmtPct(recoveryProgression.recovery_rate)} of the time (${recoveryProgression.correct_after_wrong} of ${recoveryProgression.total_after_wrong}).`
        : "You didn't have any incorrect answers to recover from — great consistency.";
    const useChart = recoveryProgression.progression_available && questionHistory.length >= 3;
    let progressionBlock;
    if (useChart) {
        progressionBlock = `
            <p class="caveat-note">Accuracy trend across the session — dots show each question result.</p>
            <div class="chart-container chart-fixed-recovery"><canvas id="progression-chart"></canvas></div>`;
    } else if (recoveryProgression.progression_available) {
        progressionBlock = `<p>First half: ${fmtPct(recoveryProgression.first_half_accuracy_pct)} accuracy (avg difficulty ${recoveryProgression.first_half_avg_difficulty.toFixed(1)}) → Second half: ${fmtPct(recoveryProgression.second_half_accuracy_pct)} (avg difficulty ${recoveryProgression.second_half_avg_difficulty.toFixed(1)}).</p>`;
    } else {
        progressionBlock = `<p>Session too short to show progression.</p>`;
    }
    return `
        <details class="report-accordion">
            <summary>Recovery &amp; Progression <span class="accordion-icon">▾</span></summary>
            <div class="accordion-body">
                <p>${recoveryLine}</p>
                ${progressionBlock}
            </div>
        </details>`;
}

function initRecoveryProgressionChart(recoveryProgression, questionHistory) {
    const canvas = document.getElementById("progression-chart");
    if (!canvas) return;
    const colors = getVerdictColors();
    const rolling = computeRollingAccuracy(questionHistory);
    const labels = rolling.map((r) => r.question_index);
    const data = rolling.map((r) => r.accuracy_pct);
    const pointBackgroundColor = rolling.map((r) => (r.correct ? colors.strong : colors.weak));
    new Chart(canvas, {
        type: "line",
        data: {
            labels,
            datasets: [{
                data,
                fill: true,
                borderColor: colors.primary,
                backgroundColor: "rgba(44, 95, 158, 0.1)",
                pointBackgroundColor,
                pointRadius: 5,
                tension: 0.2,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { title: { display: true, text: "Question #" } },
                y: { min: 0, max: 100, ticks: { callback: (v) => v + "%" } },
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => `Q${labels[ctx.dataIndex]}: ${data[ctx.dataIndex].toFixed(0)}% accuracy so far (${rolling[ctx.dataIndex].correct ? "correct" : "incorrect"})`,
                    },
                },
            },
        },
    });
}

// ─── Orchestrator ────────────────────────────────────────────────────────────
function renderReport(report) {
    const reportCard = document.getElementById("report-card");
    const sortedVerdicts = [...report.concept_verdicts].sort((a, b) => (a.mastery_pct ?? -1) - (b.mastery_pct ?? -1));

    reportCard.innerHTML = `
        ${renderHero(report.neet_score, report.time_efficiency, report.subject, report.chapter, report.ability_estimate_final)}
        ${renderNextSteps(report.next_steps)}
        ${renderConceptMasteryChart(sortedVerdicts)}
        ${renderPriorityConceptsList(report.priority_concepts)}
        ${renderStrengthConceptsList(report.strength_concepts)}
        ${renderBloomDokAccordion(report.bloom_dok_breakdown, report.question_type_breakdown)}
        ${renderErrorDonutAccordion(report.error_analysis)}
        ${renderTimeEfficiencyAccordion(report.time_efficiency, report.question_history)}
        ${renderRecoveryProgressionAccordion(report.recovery_progression, report.question_history)}
        <button class="primary-btn report-restart-btn" onclick="
            localStorage.removeItem('neet_session_id');
            location.reload();
        ">Start New Session</button>
    `;

    if (typeof Chart !== "undefined") {
        Chart.defaults.font.family = CHART_FONT_FAMILY;
    }

    const chartInitializers = [
        () => initConceptMasteryChart(sortedVerdicts),
        () => initBloomDokCharts(report.bloom_dok_breakdown, report.question_type_breakdown),
        () => initErrorDonutChart(report.error_analysis),
        () => initTimeEfficiencyChart(report.time_efficiency, report.question_history),
        () => initTimeByTypeChart(report.time_efficiency),
        () => initRecoveryProgressionChart(report.recovery_progression, report.question_history),
    ];
    for (const init of chartInitializers) {
        try {
            init();
        } catch (err) {
            console.error("Chart init failed:", err);
        }
    }
}

// ─── Boot ─────────────────────────────────────────────────────────────────────
init();
