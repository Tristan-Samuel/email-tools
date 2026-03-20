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

// Fallback: ensure all reveal elements become visible within 600ms
// in case IntersectionObserver doesn't fire (e.g. compositing issues).
setTimeout(() => {
    document.querySelectorAll(".reveal:not(.is-visible)").forEach((el) => {
        el.classList.add("is-visible");
    });
}, 600);