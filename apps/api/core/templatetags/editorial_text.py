from django import template
from django.core.exceptions import ValidationError
from django.utils.html import format_html

from core.rich_text import document_text, normalize_document, render_document

register = template.Library()


@register.simple_tag
def version_text(version):
    rich = version.structured_data.get("rich_text") if isinstance(version.structured_data, dict) else None
    try:
        document = normalize_document(rich)
        if document_text(document) == version.body.strip():
            return render_document(document)
    except ValidationError:
        pass
    return format_html('<p class="preserve-text">{}</p>', version.body)
