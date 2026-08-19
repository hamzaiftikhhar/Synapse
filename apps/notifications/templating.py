"""HTML+text rendering for transactional emails.

One Django HTML template per email type (extending `emails/base.html`) is
the single source of truth; the plain-text fallback is derived from it
rather than hand-maintained as a second copy that inevitably drifts from
the HTML. This sits *beside* `NotificationService.send_email`, not instead
of it — every existing plain-text-only email in that class is untouched.
"""

from __future__ import annotations

import re

from django.template.loader import render_to_string
from django.utils.html import strip_tags


def render_email(template_name: str, context: dict) -> tuple[str, str]:
    """Render `templates/emails/{template_name}.html` -> (html, text)."""
    html = render_to_string(f"emails/{template_name}.html", context)
    text = strip_tags(html)
    # Collapse the blank-line runs strip_tags leaves behind from stripped
    # block-level tags, without collapsing intentional paragraph breaks.
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return html, text
