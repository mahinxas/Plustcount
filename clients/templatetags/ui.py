"""Small presentation helpers shared by all templates: avatars, greeting, query strings."""

import hashlib
from urllib.parse import urlencode

from django import template
from django.utils import timezone

register = template.Library()

AVATAR_TONES = 6


@register.filter
def initials(name):
    words = [w for w in str(name or "").replace("&", " ").split() if w[:1].isalnum()]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[-1][0]).upper()


@register.filter
def tone(name):
    """Stable colour index (0-5) so the same person always gets the same avatar colour."""
    digest = hashlib.md5(str(name or "").encode("utf-8")).digest()
    return digest[0] % AVATAR_TONES


@register.simple_tag
def greeting():
    hour = timezone.localtime().hour
    if hour < 5:
        return "Good evening"
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


@register.simple_tag(takes_context=True)
def query(context, changes=None, **kwargs):
    """Current query string with some parameters changed or removed (value None or '').

    Changes come as keyword arguments, or as a dict in the first argument.
    """
    params = context["request"].GET.copy()
    params.pop("page", None)
    for key, value in {**(changes or {}), **kwargs}.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = value
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else "?"


@register.filter
def percent(part, whole):
    try:
        return round(100 * int(part) / int(whole)) if int(whole) else 0
    except (TypeError, ValueError):
        return 0


@register.simple_tag
def icon(name, size=""):
    from django.utils.html import format_html

    cls = f"icon icon-{size}" if size else "icon"
    return format_html('<svg class="{}" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="#i-{}"/></svg>', cls, name)
