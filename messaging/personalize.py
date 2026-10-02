"""Personalisation fields such as {name} and {due_date}.

Only the fields listed here are replaced. We never use str.format on user
text, so a template cannot reach into Python objects.
"""

import re

PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")

FIELDS = {
    "name": "Client name",
    "company": "Client name (same as {name})",
    "business_id": "Business ID",
    "due_date": "Due date entered when sending",
}


def unknown_placeholders(*texts):
    found = set()
    for text in texts:
        found.update(PLACEHOLDER_RE.findall(text or ""))
    return sorted(found - FIELDS.keys())


def context_for(client, due_date=""):
    return {
        "name": client.name,
        "company": client.name,
        "business_id": client.business_id,
        "due_date": due_date,
    }


def render(text, context):
    return PLACEHOLDER_RE.sub(lambda m: str(context.get(m.group(1), m.group(0))), text or "")
