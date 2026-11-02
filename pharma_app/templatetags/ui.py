"""
Small display helpers for the layout.

    {{ "Sharma Kirana Store"|initials }}  ->  "SK"
"""

from django import template

register = template.Library()


@register.filter
def initials(value, count=2):
    words = [word for word in str(value or "").replace("&", " ").split() if word[:1].isalnum()]
    letters = "".join(word[0] for word in words[: int(count)])
    return letters.upper() or "?"
