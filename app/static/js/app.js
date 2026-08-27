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

    const render = (data) => {
        const active = data.active || null;
        const latest = data.latest || null;
        const job = active || latest;
        const ai = data.ai || {};
        const pending = ai.pending || 0;
        const groqEnabled = !!ai.groq_enabled;
        const busy = !!(active && (active.status === "queued" || active.status === "running"));

        if (!job && pending <= 0) {
            panel.hidden = true;
            return;
        }
        panel.hidden = false;
        panel.classList.toggle("is-running", busy);
        panel.classList.toggle("is-error", !!(job && job.status === "error"));

        if (labelEl) {
            if (busy) labelEl.textContent = job.label || job.job_type || "Working…";
            else if (job && job.status === "cancelled") labelEl.textContent = job.label || "Cancelled";
            else if (job && job.status === "error") labelEl.textContent = job.label || "Job failed";
            else if (job && job.status === "done") labelEl.textContent = job.label || "Last job finished";
            else if (pending && groqEnabled) labelEl.textContent = `${pending} emails still need AI summaries`;
            else if (pending) labelEl.textContent = `${pending} emails have local summaries only`;
            else labelEl.textContent = "Ready";
        }
        if (messageEl) {
            if (job && job.error && job.status === "error") messageEl.textContent = job.error;
            else if (job && job.message) messageEl.textContent = job.message;
            else if (groqEnabled && pending) {
                messageEl.textContent = "Sync downloads mail quickly. AI summaries run automatically after sync, or click Analyze now.";
            } else if (!groqEnabled) {
                messageEl.textContent = "Add a Groq API key in Settings for a real inbox brief.";
            } else {
                messageEl.textContent = "";
            }
        }
        const percent = job ? job.percent || 0 : 0;
        if (fillEl) fillEl.style.width = `${percent}%`;
        if (progressEl) progressEl.setAttribute("aria-valuenow", String(percent));
        if (countsEl) {
            if (job && job.total_steps) countsEl.textContent = `${job.current_step} / ${job.total_steps}`;
            else countsEl.textContent = "";
        }
        if (logEl && job && Array.isArray(job.log)) {
            logEl.innerHTML = job.log.map((line) => `<li>${escapeHtml(line)}</li>`).join("");
        }
        if (analyzeBtn) analyzeBtn.disabled = busy || !groqEnabled || pending <= 0;
        if (cancelForm) cancelForm.hidden = !busy;
        if (cancelBtn) cancelBtn.disabled = !busy;

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
        lastStatus = active ? active.status : (latest ? latest.status : "");
    };

    if (cancelForm) {
        cancelForm.addEventListener("submit", (event) => {
            event.preventDefault();
            if (cancelBtn) cancelBtn.disabled = true;
            fetch(cancelForm.action, {
                method: "POST",
                body: new FormData(cancelForm),
                headers: { Accept: "application/json" },
            })
                .then((r) => (r.ok ? r.json() : null))
                .then(() => tick())
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
