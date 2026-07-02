const REQUEST_TIMEOUT_MS = 15000;

async function fetchWithTimeout(url, options, ms = REQUEST_TIMEOUT_MS) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), ms);
    try {
        return await fetch(url, { ...options, signal: controller.signal });
    } catch (err) {
        if (err.name === "AbortError") {
            throw new Error("Request timed out — the server may be busy generating a question. Please try again.");
        }
        throw err;
    } finally {
        clearTimeout(timer);
    }
}

async function getJSON(url) {
    const res = await fetchWithTimeout(url);
    if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error || `GET ${url} failed (${res.status})`);
    }
    return res.json();
}

async function postJSON(url, payload) {
    const res = await fetchWithTimeout(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload || {}),
    });
    if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error || `POST ${url} failed (${res.status})`);
    }
    return res.json();
}

const api = {
    getGrades: () => getJSON("/api/taxonomy/grades"),
    getChapters: (gradeLevel, subject) => {
        const params = new URLSearchParams({ grade_level: gradeLevel });
        if (subject) params.set("subject", subject);
        return getJSON(`/api/taxonomy/chapters?${params.toString()}`);
    },
    startSession: (payload) => postJSON("/api/sessions", payload),
    getCurrentQuestion: (sessionId) => getJSON(`/api/sessions/${sessionId}/current`),
    submitAnswer: (sessionId, payload) => postJSON(`/api/sessions/${sessionId}/answer`, payload),
    getReport: (sessionId) => getJSON(`/api/sessions/${sessionId}/report`).catch(() => null),
    generateReport: (sessionId) => postJSON(`/api/sessions/${sessionId}/report`, {}),
};
