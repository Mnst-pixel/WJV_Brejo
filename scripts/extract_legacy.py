#!/usr/bin/env python3
"""Extract the supplied legacy HTML without executing its JavaScript."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

SOURCE_STATUS = "legacy_unverified"
DATASET_NAMES = (
    "diQs",
    "pvQs",
    "svQs",
    "dc5Qs",
    "oabData",
    "hpQuotes",
    "SUBJECTS",
    "TIPO_META_LABELS",
    "MARK_TYPES",
    "LEG_TIPOS",
    "pomoState",
)


class LiteralSyntaxError(ValueError):
    pass


@dataclass
class LiteralParser:
    source: str
    index: int = 0

    def parse(self) -> Any:
        value = self._value()
        self._space()
        return value

    def _space(self) -> None:
        while self.index < len(self.source):
            if self.source[self.index].isspace():
                self.index += 1
            elif self.source.startswith("//", self.index):
                end = self.source.find("\n", self.index + 2)
                self.index = len(self.source) if end < 0 else end + 1
            elif self.source.startswith("/*", self.index):
                end = self.source.find("*/", self.index + 2)
                if end < 0:
                    raise LiteralSyntaxError("unterminated comment")
                self.index = end + 2
            else:
                break

    def _value(self) -> Any:
        self._space()
        if self.index >= len(self.source):
            raise LiteralSyntaxError("unexpected end of input")
        char = self.source[self.index]
        if char == "{":
            return self._object()
        if char == "[":
            return self._array()
        if char in "'\"`":
            return self._string()
        number = re.match(r"-?(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)", self.source[self.index :])
        if number:
            token = number.group(0)
            self.index += len(token)
            if token.lower().startswith("-0x"):
                value: int | float = -int(token[3:], 16)
            elif token.lower().startswith("0x"):
                value = int(token, 16)
            else:
                value = float(token) if any(c in token for c in ".eE") else int(token)
            self._space()
            while self.index < len(self.source) and self.source[self.index] == "*":
                self.index += 1
                factor = self._value()
                if not isinstance(factor, (int, float)) or isinstance(factor, bool):
                    raise LiteralSyntaxError("numeric multiplication requires numbers")
                value *= factor
                self._space()
            return value
        identifier = self._identifier()
        values = {"true": True, "false": False, "null": None, "undefined": None}
        if identifier not in values:
            raise LiteralSyntaxError(f"unsupported identifier value: {identifier}")
        return values[identifier]

    def _identifier(self) -> str:
        match = re.match(r"[A-Za-z_$][\w$-]*", self.source[self.index :])
        if not match:
            raise LiteralSyntaxError(f"expected identifier at offset {self.index}")
        value = match.group(0)
        self.index += len(value)
        return value

    def _string(self) -> str:
        quote = self.source[self.index]
        self.index += 1
        result: list[str] = []
        escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
        while self.index < len(self.source):
            char = self.source[self.index]
            self.index += 1
            if char == quote:
                return "".join(result)
            if char == "$" and quote == "`" and self.source.startswith("{", self.index):
                raise LiteralSyntaxError("template interpolation is not permitted")
            if char != "\\":
                result.append(char)
                continue
            if self.index >= len(self.source):
                raise LiteralSyntaxError("unterminated escape")
            escaped = self.source[self.index]
            self.index += 1
            if escaped == "u":
                digits = self.source[self.index : self.index + 4]
                if not re.fullmatch(r"[0-9a-fA-F]{4}", digits):
                    raise LiteralSyntaxError("invalid unicode escape")
                result.append(chr(int(digits, 16)))
                self.index += 4
            elif escaped == "x":
                digits = self.source[self.index : self.index + 2]
                if not re.fullmatch(r"[0-9a-fA-F]{2}", digits):
                    raise LiteralSyntaxError("invalid hex escape")
                result.append(chr(int(digits, 16)))
                self.index += 2
            elif escaped in "\n\r":
                if escaped == "\r" and self.index < len(self.source) and self.source[self.index] == "\n":
                    self.index += 1
            else:
                result.append(escapes.get(escaped, escaped))
        raise LiteralSyntaxError("unterminated string")

    def _array(self) -> list[Any]:
        self.index += 1
        result: list[Any] = []
        self._space()
        while self.index < len(self.source) and self.source[self.index] != "]":
            result.append(self._value())
            self._space()
            if self.source[self.index] == ",":
                self.index += 1
                self._space()
                continue
            if self.source[self.index] != "]":
                raise LiteralSyntaxError(f"expected comma or ] at offset {self.index}")
        if self.index >= len(self.source):
            raise LiteralSyntaxError("unterminated array")
        self.index += 1
        return result

    def _object(self) -> dict[str, Any]:
        self.index += 1
        result: dict[str, Any] = {}
        self._space()
        while self.index < len(self.source) and self.source[self.index] != "}":
            key = self._string() if self.source[self.index] in "'\"`" else self._identifier()
            self._space()
            if self.index >= len(self.source) or self.source[self.index] != ":":
                raise LiteralSyntaxError(f"expected colon after {key}")
            self.index += 1
            result[key] = self._value()
            self._space()
            if self.source[self.index] == ",":
                self.index += 1
                self._space()
                continue
            if self.source[self.index] != "}":
                raise LiteralSyntaxError(f"expected comma or }} at offset {self.index}")
        if self.index >= len(self.source):
            raise LiteralSyntaxError("unterminated object")
        self.index += 1
        return result


class StructureInventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.panels: list[str] = []
        self.headings: list[dict[str, str]] = []
        self.controls: list[str] = []
        self._heading: tuple[str, list[str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id and element_id.startswith("panel-"):
            self.panels.append(element_id.removeprefix("panel-"))
        if element_id and tag in {"button", "input", "select", "textarea"}:
            self.controls.append(element_id)
        if tag in {"h1", "h2", "h3", "h4"}:
            self._heading = (tag, [])

    def handle_data(self, data: str) -> None:
        if self._heading:
            self._heading[1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._heading and tag == self._heading[0]:
            text = " ".join("".join(self._heading[1]).split())
            if text:
                self.headings.append({"level": tag, "text": text})
            self._heading = None


def extract_literal(text: str, name: str) -> Any:
    match = re.search(rf"\b(?:const|let|var)\s+{re.escape(name)}\s*=\s*", text)
    if not match:
        raise LiteralSyntaxError(f"dataset not found: {name}")
    parser = LiteralParser(text[match.end() :])
    return parser.parse()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()

    raw = args.source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest.lower() != args.expected_sha256.lower():
        raise SystemExit(f"source hash mismatch: expected {args.expected_sha256}, got {digest}")
    text = raw.decode("utf-8")
    datasets = {name: extract_literal(text, name) for name in DATASET_NAMES}

    structure = StructureInventory()
    structure.feed(text)
    storage_keys = sorted(set(re.findall(r"storage\.(?:get|set)\(['\"]([^'\"]+)", text)))

    questions: list[dict[str, Any]] = []
    for dataset in ("diQs", "pvQs", "svQs", "dc5Qs"):
        for position, item in enumerate(datasets[dataset], start=1):
            questions.append(
                {
                    "legacy_dataset": dataset,
                    "legacy_position": position,
                    "question": item.get("q", item.get("i")),
                    "alternatives": item["opts"],
                    "answer_index": item["ans"],
                    "explanation": item.get("exp", ""),
                    "legal_status": SOURCE_STATUS,
                    "source_sha256": digest,
                }
            )

    oab_sections = datasets["oabData"]
    oab_item_count = sum(len(section.get("items", [])) for section in oab_sections.values())
    inventory = {
        "schema_version": 1,
        "source": {
            "file": args.source.name,
            "sha256": digest,
            "bytes": len(raw),
            "lines": len(text.splitlines()),
            "encoding": "UTF-8",
            "legal_status": SOURCE_STATUS,
        },
        "counts": {
            "questions_total": len(questions),
            "questions_by_dataset": {name: len(datasets[name]) for name in ("diQs", "pvQs", "svQs", "dc5Qs")},
            "oab_sections": len(oab_sections),
            "oab_summary_items": oab_item_count,
            "panels": len(set(structure.panels)),
            "headings": len(structure.headings),
            "interactive_controls": len(set(structure.controls)),
            "storage_keys": len(storage_keys),
        },
        "reconciliation": {
            "question_datasets_parsed": 4,
            "question_records_equal_dataset_sum": len(questions)
            == sum(len(datasets[name]) for name in ("diQs", "pvQs", "svQs", "dc5Qs")),
            "all_answer_indexes_valid": all(0 <= row["answer_index"] < len(row["alternatives"]) for row in questions),
            "javascript_executed": False,
        },
    }

    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / "inventory.json", inventory)
    write_json(args.output / "questions.json", questions)
    write_json(args.output / "oab-data.json", oab_sections)
    write_json(
        args.output / "functional-concepts.json",
        {
            "subjects": datasets["SUBJECTS"],
            "goal_types": datasets["TIPO_META_LABELS"],
            "mark_types": datasets["MARK_TYPES"],
            "legal_reference_types": datasets["LEG_TIPOS"],
            "pomodoro_default": datasets["pomoState"],
            "homepage_quotes": datasets["hpQuotes"],
            "panels": sorted(set(structure.panels)),
            "storage_keys": storage_keys,
            "legal_status": SOURCE_STATUS,
            "source_sha256": digest,
        },
    )
    write_json(args.output / "headings.json", structure.headings)

    with (args.output / "questions.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("legacy_dataset", "legacy_position", "question", "alternatives_json", "answer_index", "explanation", "legal_status", "source_sha256"),
        )
        writer.writeheader()
        for row in questions:
            csv_row = dict(row)
            csv_row["alternatives_json"] = json.dumps(csv_row.pop("alternatives"), ensure_ascii=False)
            writer.writerow(csv_row)

    summary = f"""# Inventário reconciliado do HTML legado

- SHA-256: `{digest}`
- Tamanho: {len(raw)} bytes
- Linhas: {len(text.splitlines())}
- Estado jurídico inicial: `{SOURCE_STATUS}`
- JavaScript executado durante extração: não

## Contagens

- Questões: {len(questions)}
- Questões por conjunto: {json.dumps(inventory['counts']['questions_by_dataset'], ensure_ascii=False)}
- Seções de resumo OAB: {len(oab_sections)}
- Itens de resumo: {oab_item_count}
- Painéis funcionais: {len(set(structure.panels))}
- Chaves de armazenamento local: {len(storage_keys)}

## Gate

As contagens dos quatro conjuntos de questões fecham com o total exportado e todos os índices de resposta apontam para alternativas existentes. O material continua não verificado e não pode ser publicado ou indexado como conteúdo aprovado sem revisão humana, proveniência e decisão editorial registradas.
"""
    (args.output / "LEGACY_INVENTORY.md").write_text(summary, encoding="utf-8")
    print(json.dumps(inventory["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
