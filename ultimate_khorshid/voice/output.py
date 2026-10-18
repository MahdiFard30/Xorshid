"""Separate spoken answers from the application's display-only tool footer."""
import re

_FOOTER = re.compile(
    r'\n\s*---\s*\n\s*\*?⚙️?\s*\d+\s+ابزار اجرا شد'
    r'[^\n]*\|\s*ایجنت:[^\n]*\|\s*مدل:[^\n]*\s*\Z'
)


def speech_text(result):
    metadata = getattr(result, 'metadata', None) or {}
    text = metadata.get('speech_content', getattr(result, 'content', ''))
    return _FOOTER.sub('', str(text)).strip()
