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
