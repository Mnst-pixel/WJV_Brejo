"""Bounded rich text AST. No HTML, URLs, attributes or executable nodes are stored."""
from django.core.exceptions import ValidationError
from django.utils.html import format_html, format_html_join

SCHEMA = "kairos-rich-text-v1"
BLOCKS = {"paragraph", "heading2", "heading3", "quote", "bullet_list", "ordered_list"}


def normalize_document(value):
    def reject():
        raise ValidationError("A formatação do texto é inválida. Confira o conteúdo no editor visual.")

    if not isinstance(value, dict) or set(value) != {"schema", "blocks"} or value["schema"] != SCHEMA:
        reject()
    blocks = value["blocks"]
    if not isinstance(blocks, list) or not 1 <= len(blocks) <= 1000:
        reject()
    spans_seen = chars_seen = items_seen = 0

    def inline(items):
        nonlocal spans_seen, chars_seen
        if not isinstance(items, list) or len(items) > 5000:
            reject()
        output = []
        for item in items:
            if not isinstance(item, dict) or set(item) - {"text", "bold", "italic"} or not isinstance(item.get("text"), str):
                reject()
            if any(type(item.get(mark, False)) is not bool for mark in ("bold", "italic")):
                reject()
            spans_seen += 1
            chars_seen += len(item["text"])
            if spans_seen > 5000 or chars_seen > 100_000 or "\x00" in item["text"]:
                reject()
            normalized = {"text": item["text"].replace("\r\n", "\n").replace("\r", "\n")}
            normalized.update({mark: True for mark in ("bold", "italic") if item.get(mark)})
            output.append(normalized)
        return output

    normalized = []
    for block in blocks:
        if not isinstance(block, dict) or not isinstance(block.get("type"), str) or block["type"] not in BLOCKS:
            reject()
        kind = block["type"]
        if kind in {"bullet_list", "ordered_list"}:
            if set(block) != {"type", "items"} or not isinstance(block["items"], list) or not block["items"]:
                reject()
            items_seen += len(block["items"])
            if items_seen > 1000:
                reject()
            normalized.append({"type": kind, "items": [inline(item) for item in block["items"]]})
        else:
            if set(block) != {"type", "content"}:
                reject()
            normalized.append({"type": kind, "content": inline(block["content"])})
    result = {"schema": SCHEMA, "blocks": normalized}
    if len(document_text(result)) > 100_000:
        reject()
    return result


def document_text(document):
    def text(spans):
        return "".join(span["text"] for span in spans)
    return "\n\n".join("\n".join(text(item) for item in block["items"]) if "items" in block else text(block["content"]) for block in document["blocks"]).strip()


def render_document(value):
    document = normalize_document(value)
    def inline(spans):
        rendered = []
        for span in spans:
            text = format_html("{}", span["text"])
            if span.get("bold"):
                text = format_html("<strong>{}</strong>", text)
            if span.get("italic"):
                text = format_html("<em>{}</em>", text)
            rendered.append((text,))
        return format_html_join("", "{}", rendered)
    templates = {"paragraph": "<p>{}</p>", "heading2": "<h2>{}</h2>", "heading3": "<h3>{}</h3>", "quote": "<blockquote>{}</blockquote>", "bullet_list": "<ul>{}</ul>", "ordered_list": "<ol>{}</ol>"}
    rendered = []
    for block in document["blocks"]:
        content = format_html_join("", "<li>{}</li>", ((inline(item),) for item in block["items"])) if "items" in block else inline(block["content"])
        rendered.append((format_html(templates[block["type"]], content),))
    return format_html_join("", "{}", rendered)
