"""Sanitize email HTML for safe display with load-on-demand remote images."""

from __future__ import annotations

import re

import nh3

_IMG_SRC_RE = re.compile(
    r'(<img\b[^>]*\bsrc\s*=\s*)(["\']?)([^"\'>\s]+)\2',
    re.I,
)
_BLOCKED_IMG_SCHEMES = ("cid:", "data:", "javascript:")


def _image_placeholder_tag(src: str, original: str) -> str:
    """Replace remote images with placeholders; inline blocked schemes as text."""
    lower = src.strip().lower()
    if lower.startswith(_BLOCKED_IMG_SCHEMES):
        label = "embedded image"
        alt_match = re.search(r'\balt\s*=\s*["\']([^"\']*)["\']', original, re.I)
        if alt_match and alt_match.group(1).strip():
            label = alt_match.group(1).strip()
        safe = nh3.clean_text(label)
        return f'<span class="email-img-placeholder">[{safe}]</span>'
    safe_src = nh3.clean_text(src)
    return (
        f'<span class="email-img-placeholder email-img-remote" data-src="{safe_src}" '
        f'role="img" aria-label="Image (not loaded)">[Image]</span>'
    )


def _defer_remote_images(html: str) -> str:
    if not html or "<img" not in html.lower():
        return html

    def _replace(match: re.Match[str]) -> str:
        prefix, quote, src = match.group(1), match.group(2), match.group(3)
        del prefix, quote
        lower = src.lower()
        if lower.startswith("http://") or lower.startswith("https://"):
            return _image_placeholder_tag(src, match.group(0))
        if lower.startswith(_BLOCKED_IMG_SCHEMES):
            return _image_placeholder_tag(src, match.group(0))
        return match.group(0)

    return _IMG_SRC_RE.sub(_replace, html)


def sanitize_email_html(raw_html: str) -> str:
    """Return safe HTML suitable for email detail view."""
    if not raw_html or not raw_html.strip():
        return ""
    prepared = _defer_remote_images(raw_html)
    cleaned = nh3.clean(
        prepared,
        tags={
            "a", "abbr", "b", "blockquote", "br", "caption", "code", "col",
            "colgroup", "div", "em", "h1", "h2", "h3", "h4", "h5", "h6",
            "hr", "i", "img", "li", "ol", "p", "pre", "span", "strong",
            "sub", "sup", "table", "tbody", "td", "tfoot", "th", "thead",
            "tr", "u", "ul",
        },
        attributes={
            "a": {"href", "title"},
            "img": {"alt", "title", "width", "height"},
            "td": {"colspan", "rowspan"},
            "th": {"colspan", "rowspan"},
            "span": {"class", "data-src", "role", "aria-label"},
        },
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
    )
    return cleaned
