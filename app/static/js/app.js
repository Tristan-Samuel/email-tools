const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function applyTheme(mode) {
    const stored = mode || localStorage.getItem("theme") || "system";
    localStorage.setItem("theme", stored);
    const dark =
        stored === "dark" ||
        (stored === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
    document.documentElement.dataset.themeMode = stored;
    document.querySelectorAll("[data-theme-pick]").forEach((btn) => {
        btn.classList.toggle("theme-toggle-btn--active", btn.dataset.themePick === stored);
    });
}

applyTheme();
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (localStorage.getItem("theme") === "system" || !localStorage.getItem("theme")) {
        applyTheme("system");
    }
});
document.querySelectorAll("[data-theme-pick]").forEach((btn) => {
    btn.addEventListener("click", () => applyTheme(btn.dataset.themePick));
});

if (!prefersReducedMotion) {
    const observer = new IntersectionObserver(
        (entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    entry.target.classList.add("is-visible");
                    observer.unobserve(entry.target);
                }
            });
        },
        { threshold: 0, rootMargin: "0px 0px 80px 0px" }
    );

    document.querySelectorAll(".reveal").forEach((element) => {
        observer.observe(element);
    });

    setTimeout(() => {
        document.querySelectorAll(".reveal:not(.is-visible)").forEach((el) => {
            el.classList.add("is-visible");
        });
    }, 600);
} else {
    document.querySelectorAll(".reveal").forEach((el) => {
        el.classList.add("is-visible");
    });
}

function addTagRule(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const row = document.createElement("div");
    row.className = "tag-rule-row";
    row.innerHTML = `
        <select name="rule_field">
            <option value="sender">Sender</option>
            <option value="recipient">Recipient</option>
            <option value="subject">Subject</option>
            <option value="body">Body</option>
            <option value="category">Category</option>
        </select>
        <select name="rule_operator">
            <option value="contains">contains</option>
            <option value="equals">equals</option>
            <option value="starts_with">starts with</option>
            <option value="ends_with">ends with</option>
            <option value="not_contains">does not contain</option>
        </select>
        <input type="text" name="rule_value" placeholder="value" required
               style="flex:1;min-width:120px;padding:7px 10px;border-radius:6px;border:1.5px solid var(--line);background:var(--bg);font:inherit;font-size:.88rem">
        <button type="button" class="btn btn-ghost" style="padding:5px 10px;font-size:.8rem"
                onclick="this.closest('.tag-rule-row').remove()">✕</button>
    `;
    container.appendChild(row);
}

window.addRule = addTagRule;
window.addTagRule = addTagRule;

const ACTIVITY_PHASES = [
    { key: "fetch", label: "Fetch" },
    { key: "summarize", label: "Summarize" },
    { key: "tag", label: "Tag" },
    { key: "brief", label: "Brief" },
];
const ACTIVITY_DISMISS_KEY = "activityDismissedJobId";

function findIncompletePhase(phases, busy) {
    if (!phases || !busy) return null;
    for (const phase of ACTIVITY_PHASES) {
        const entry = phases[phase.key] || {};
        const total = Number(entry.total || 0);
        const current = Number(entry.current || 0);
        if (total > 0 && current < total) return phase;
    }
    return null;
}

function initActivityPanel() {
    const panel = document.getElementById("activity-panel");
    if (!panel) return;
    const url = panel.dataset.poll;
    const labelEl = document.getElementById("activity-label");
    const messageEl = document.getElementById("activity-message");
    const fillEl = document.getElementById("activity-progress-fill");
    const progressEl = document.getElementById("activity-progress");
    const countsEl = document.getElementById("activity-counts");
    const logEl = document.getElementById("activity-log");
    const toggle = document.getElementById("activity-log-toggle");
    const analyzeBtn = document.getElementById("activity-analyze-btn");
    const cancelForm = document.getElementById("activity-cancel-form");
    const cancelBtn = document.getElementById("activity-cancel-btn");
    const dismissBtn = document.getElementById("activity-dismiss-btn");
    const phasesEl = document.getElementById("activity-phases");
    const meterEl = document.getElementById("activity-meter");
    let lastActiveId = null;
    let lastStatus = "";

    if (toggle && logEl) {
        toggle.addEventListener("click", () => {
            const open = logEl.hasAttribute("hidden");
            if (open) logEl.removeAttribute("hidden");
            else logEl.setAttribute("hidden", "");
            toggle.setAttribute("aria-expanded", open ? "true" : "false");
        });
    }

    const hidePanel = () => {
        panel.hidden = true;
        panel.classList.remove("is-running", "is-error", "activity-panel--idle");
    };

    const render = (data) => {
        const active = data.active || null;
        const latest = data.latest || null;
        const ai = data.ai || {};
        const pending = ai.pending || 0;
        const groqEnabled = !!ai.groq_enabled;
        const busy = !!(active && (active.status === "queued" || active.status === "running"));
        const dismissedId = sessionStorage.getItem(ACTIVITY_DISMISS_KEY) || "";
        const job = busy ? active : null;

        if (!busy && latest && (latest.status === "cancelled" || latest.status === "done")) {
            sessionStorage.setItem(ACTIVITY_DISMISS_KEY, String(latest.id));
        }

        const shouldHide =
            !busy &&
            (!latest || dismissedId === String(latest.id) || latest.status === "cancelled") &&
            pending <= 0;

        if (shouldHide) {
            hidePanel();
            return;
        }

        panel.hidden = false;
        panel.classList.toggle("is-running", busy);
        panel.classList.toggle("is-error", !!(latest && latest.status === "error" && !busy));
        panel.classList.toggle("activity-panel--idle", !busy && pending > 0);

        const displayJob = job || latest;

        if (phasesEl) phasesEl.hidden = !busy;
        if (meterEl) meterEl.hidden = !busy;
        if (toggle) toggle.hidden = !busy;
        if (logEl && !busy) logEl.setAttribute("hidden", "");

        if (labelEl) {
            if (busy) labelEl.textContent = displayJob.label || displayJob.job_type || "Working…";
            else if (latest && latest.status === "error") labelEl.textContent = latest.label || "Job failed";
            else if (pending && groqEnabled) labelEl.textContent = `${pending} emails still need AI summaries`;
            else if (pending) labelEl.textContent = `${pending} emails have local summaries only`;
            else labelEl.textContent = displayJob?.label || "Ready";
        }
        if (messageEl) {
            if (busy && displayJob?.message) messageEl.textContent = displayJob.message;
            else if (latest && latest.error && latest.status === "error") messageEl.textContent = latest.error;
            else if (groqEnabled && pending) {
                messageEl.textContent =
                    "Sync downloads mail quickly. AI summaries run automatically after sync, or click Analyze now.";
            } else if (!groqEnabled) {
                messageEl.textContent = "Add a Groq API key in Settings for a real inbox brief.";
            } else {
                messageEl.textContent = "";
            }
        }

        const percent = displayJob ? displayJob.percent || 0 : 0;
        if (fillEl) fillEl.style.width = `${percent}%`;
        if (progressEl) progressEl.setAttribute("aria-valuenow", String(percent));
        if (countsEl) {
            if (busy && displayJob?.phases) {
                const phase = findIncompletePhase(displayJob.phases, true);
                if (phase) {
                    const entry = displayJob.phases[phase.key] || {};
                    countsEl.textContent = `${entry.current || 0} / ${entry.total || 0} (${phase.label})`;
                } else if (displayJob.total_steps) {
                    countsEl.textContent = `${displayJob.current_step} / ${displayJob.total_steps}`;
                } else {
                    countsEl.textContent = `${percent}%`;
                }
            } else {
                countsEl.textContent = "";
            }
        }

        ACTIVITY_PHASES.forEach((phase) => {
            const fill = document.querySelector(`[data-phase-fill="${phase.key}"]`);
            const counts = document.querySelector(`[data-phase-counts="${phase.key}"]`);
            const row = document.querySelector(`.activity-phase-row[data-phase="${phase.key}"]`);
            const entry = displayJob && displayJob.phases ? displayJob.phases[phase.key] || {} : {};
            const total = Number(entry.total || 0);
            const current = Number(entry.current || 0);
            const phasePct = total > 0 ? Math.min(100, Math.round((current * 100) / total)) : 0;
            if (fill) fill.style.width = `${phasePct}%`;
            if (counts) {
                counts.textContent = total > 0 ? `${current} / ${total}` : "";
            }
            if (row) {
                row.classList.toggle("is-active", busy && total > 0 && current < total);
                row.classList.toggle("is-done", total > 0 && current >= total);
            }
        });

        if (logEl && displayJob && Array.isArray(displayJob.log)) {
            logEl.innerHTML = displayJob.log.map((line) => `<li>${escapeHtml(line)}</li>`).join("");
        }
        if (analyzeBtn) analyzeBtn.disabled = busy || !groqEnabled || pending <= 0;
        if (cancelForm) cancelForm.hidden = !busy;
        if (cancelBtn) cancelBtn.disabled = !busy;
        if (dismissBtn) dismissBtn.hidden = busy;

        if (
            lastStatus === "running" &&
            !busy &&
            latest &&
            latest.status === "done" &&
            lastActiveId &&
            latest.id === lastActiveId &&
            document.querySelector("[data-reload-on-job]")
        ) {
            window.location.reload();
        }
        lastActiveId = active ? active.id : lastActiveId;
        lastStatus = active ? active.status : latest ? latest.status : "";
    };

    if (dismissBtn) {
        dismissBtn.addEventListener("click", () => {
            const latestId = sessionStorage.getItem(ACTIVITY_DISMISS_KEY);
            if (!latestId && panel.dataset.latestJobId) {
                sessionStorage.setItem(ACTIVITY_DISMISS_KEY, panel.dataset.latestJobId);
            } else if (!latestId) {
                sessionStorage.setItem(ACTIVITY_DISMISS_KEY, "dismissed");
            }
            hidePanel();
        });
    }

    if (cancelForm) {
        cancelForm.addEventListener("submit", (event) => {
            event.preventDefault();
            if (lastActiveId) sessionStorage.setItem(ACTIVITY_DISMISS_KEY, String(lastActiveId));
            if (cancelBtn) cancelBtn.disabled = true;
            fetch(cancelForm.action, {
                method: "POST",
                body: new FormData(cancelForm),
                headers: { Accept: "application/json" },
            })
                .then((r) => (r.ok ? r.json() : null))
                .then(() => {
                    hidePanel();
                    tick();
                })
                .catch(() => {
                    cancelForm.submit();
                });
        });
    }

    const tick = () => {
        fetch(url, { headers: { Accept: "application/json" } })
            .then((r) => (r.ok ? r.json() : null))
            .then((data) => {
                if (data) render(data);
            })
            .catch(() => {});
    };
    tick();
    setInterval(tick, 2000);
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

initActivityPanel();

function initAiPromptChips() {
    document.querySelectorAll("[data-ai-prompt-go]").forEach((chip) => {
        chip.addEventListener("click", () => {
            const prompt = chip.dataset.aiPromptGo || "";
            if (!prompt) return;
            const url = new URL("/search", window.location.origin);
            url.searchParams.set("query", prompt);
            url.searchParams.set("ai", "1");
            window.location.href = url.toString();
        });
    });
}

function initCommandPalette() {
    const palette = document.getElementById("command-palette");
    const input = document.getElementById("command-palette-input");
    const results = document.getElementById("command-palette-results");
    if (!palette || !input || !results) return;

    const commands = [
        { label: "Today", href: "/today", type: "nav" },
        { label: "All mail", href: "/inbox", type: "nav" },
        { label: "AI Search", href: "/search", type: "nav" },
        { label: "Assignments", href: "/assignments", type: "nav" },
        { label: "Settings", href: "/settings", type: "nav" },
        { label: "Guide", href: "/guide", type: "nav" },
        { label: "AI: List assignments", href: "/search?ai=1&query=List+assignments+I+need+to+get+done", type: "ai" },
        { label: "AI: Waiting on me", href: "/search?ai=1&query=What+emails+are+waiting+on+me", type: "ai" },
        { label: "AI: This week", href: "/search?ai=1&query=What+do+I+need+to+handle+this+week", type: "ai" },
    ];

    const render = (filter) => {
        const q = (filter || "").trim().toLowerCase();
        const matches = commands.filter((c) => !q || c.label.toLowerCase().includes(q));
        results.innerHTML = matches
            .map(
                (c) =>
                    `<li><button type="button" data-href="${escapeHtml(c.href)}">${escapeHtml(c.label)}</button></li>`
            )
            .join("");
        results.querySelectorAll("button").forEach((btn) => {
            btn.addEventListener("click", () => {
                window.location.href = btn.dataset.href;
            });
        });
    };

    const open = () => {
        palette.hidden = false;
        input.value = "";
        render("");
        input.focus();
    };
    const close = () => {
        palette.hidden = true;
    };

    document.addEventListener("keydown", (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
            if (e.target.matches("input, textarea, select") && e.target.id !== "command-palette-input") return;
            e.preventDefault();
            open();
        }
        if (e.key === "Escape" && !palette.hidden) close();
    });

    palette.querySelectorAll("[data-close-palette]").forEach((el) => {
        el.addEventListener("click", close);
    });
    input.addEventListener("input", () => render(input.value));
}

function initKeyboardSheet() {
    const sheet = document.getElementById("keyboard-sheet");
    if (!sheet) return;
    const enabled = document.body.dataset.keyboardShortcuts !== "0";
    const open = () => {
        sheet.hidden = false;
    };
    const close = () => {
        sheet.hidden = true;
    };
    document.addEventListener("keydown", (e) => {
        if (!enabled) return;
        if (e.key === "?" && !e.target.matches("input, textarea, select")) {
            e.preventDefault();
            open();
        }
        if (e.key === "Escape" && !sheet.hidden) close();
    });
    sheet.querySelectorAll("[data-close-keyboard]").forEach((el) => {
        el.addEventListener("click", close);
    });
}

initAiPromptChips();
initCommandPalette();
initKeyboardSheet();
