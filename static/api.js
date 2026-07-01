async function getJSON(url) {
    const res = await fetch(url);
    if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error || `GET ${url} failed (${res.status})`);
    }
    return res.json();
}

async function postJSON(url, payload) {
    const res = await fetch(url, {
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
