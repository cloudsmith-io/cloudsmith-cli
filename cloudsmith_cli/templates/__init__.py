"""Templates for the Cloudsmith CLI (HTML pages, config-file templates).

Templates use ``<!-- KEY_PLACEHOLDER -->`` markers so the files stay valid
HTML/XML and get normal editor validation; :func:`render` substitutes them.
"""

import os


def template_path(name):
    """Return the absolute path to the template *name* in this package."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


def render(name, **context):
    """Render template *name*, replacing ``<!-- KEY_PLACEHOLDER -->`` markers.

    Each ``context`` key ``foo`` replaces ``<!-- FOO_PLACEHOLDER -->`` with its
    value (empty string when falsy).  Callers are responsible for escaping
    values for the target format (e.g. XML-escaping).
    """
    with open(template_path(name), encoding="utf-8") as handle:
        content = handle.read()
    for key, value in context.items():
        placeholder = f"<!-- {key.upper()}_PLACEHOLDER -->"
        content = content.replace(placeholder, value if value else "")
    return content
