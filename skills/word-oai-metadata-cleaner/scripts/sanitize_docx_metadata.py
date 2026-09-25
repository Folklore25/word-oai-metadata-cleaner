#!/usr/bin/env python3
"""Audit and conservatively sanitize ChatGPT/OpenAI metadata in DOCX packages."""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from copy import copy
from pathlib import Path, PurePosixPath
from typing import Iterable
from xml.etree import ElementTree as ET


AI_PATTERN = re.compile(
    r"chatgpt|\bgpt(?:-?[0-9]+(?:\.[0-9]+)?)?\b|openai|"
    r"chat\.openai\.com|chatgpt\.com|openai\.com|"
    r"oaistatic\.com|oaiusercontent\.com",
    re.IGNORECASE,
)

CORE_CLEAR_TAGS = {
    "creator",
    "lastModifiedBy",
    "title",
    "subject",
    "description",
    "keywords",
    "category",
    "contentStatus",
    "identifier",
    "language",
    "version",
}
APP_CLEAR_TAGS = {"Company", "Manager", "HyperlinkBase"}
IDENTITY_ATTRS = {"author", "initials", "userId", "providerId", "email"}
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
REL_TAG = f"{{{REL_NS}}}Relationship"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
OFFICE_REL_ID = f"{{{OFFICE_REL_NS}}}id"


def local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def classify_part(name: str) -> str:
    if name.startswith("docProps/"):
        return "package_metadata"
    if name.startswith("customXml/"):
        return "custom_xml"
    if "/comments" in name or name.endswith("people.xml"):
        return "comment_identity_or_text"
    if name.endswith(".rels"):
        return "relationship"
    if name.startswith("word/header") or name.startswith("word/footer"):
        return "header_or_footer_content"
    if name == "word/document.xml":
        return "visible_document_content"
    if name.startswith("word/"):
        return "word_content_or_settings"
    return "other_package_part"


def is_xml_part(name: str) -> bool:
    return name.endswith((".xml", ".rels")) or name == "[Content_Types].xml"


def parse_xml(data: bytes) -> ET.Element:
    """Parse XML while retaining declared OOXML namespace prefixes."""
    for _event, namespace in ET.iterparse(io.BytesIO(data), events=("start-ns",)):
        prefix, uri = namespace
        prefix = prefix or ""
        if prefix in {"xml", "xmlns"} or re.fullmatch(r"ns\d+", prefix):
            continue
        ET.register_namespace(prefix, uri)
    return ET.fromstring(data)


def find_matches(name: str, data: bytes) -> list[dict[str, str]]:
    text = data.decode("utf-8", errors="replace")
    findings: list[dict[str, str]] = []
    for match in AI_PATTERN.finditer(text):
        start = max(0, match.start() - 80)
        end = min(len(text), match.end() + 120)
        context = re.sub(r"\s+", " ", text[start:end]).strip()
        findings.append(
            {
                "part": name,
                "classification": classify_part(name),
                "match": match.group(0),
                "context": context,
            }
        )
    return findings


def scan_package(path: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    with zipfile.ZipFile(path, "r") as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            findings.extend(find_matches(info.filename, archive.read(info.filename)))
        if archive.comment and AI_PATTERN.search(
            archive.comment.decode("utf-8", errors="replace")
        ):
            findings.append(
                {
                    "part": "ZIP comment",
                    "classification": "package_metadata",
                    "match": "AI-related ZIP comment",
                    "context": archive.comment.decode("utf-8", errors="replace"),
                }
            )
    return findings


def serialize_xml(root: ET.Element, original: bytes) -> bytes:
    declaration = original.lstrip().startswith(b"<?xml")
    return ET.tostring(root, encoding="utf-8", xml_declaration=declaration)


def clear_matching_properties(
    name: str, data: bytes, clear_all_personal: bool
) -> tuple[bytes, int]:
    try:
        root = parse_xml(data)
    except ET.ParseError:
        return data, 0
    changes = 0

    if name == "docProps/core.xml":
        for element in root.iter():
            tag = local_name(element.tag)
            should_clear = clear_all_personal and tag in {"creator", "lastModifiedBy"}
            should_clear = should_clear or (
                tag in CORE_CLEAR_TAGS
                and element.text is not None
                and AI_PATTERN.search(element.text)
            )
            if should_clear and element.text:
                element.text = None
                changes += 1

    elif name == "docProps/app.xml":
        for element in root.iter():
            tag = local_name(element.tag)
            should_clear = clear_all_personal and tag in {"Company", "Manager"}
            should_clear = should_clear or (
                tag in APP_CLEAR_TAGS
                and element.text is not None
                and AI_PATTERN.search(element.text)
            )
            if should_clear and element.text:
                element.text = None
                changes += 1

    elif name == "docProps/custom.xml":
        for child in list(root):
            serialized = ET.tostring(child, encoding="unicode")
            property_name = child.attrib.get("name", "")
            if (
                clear_all_personal
                or AI_PATTERN.search(property_name)
                or AI_PATTERN.search(serialized)
            ):
                root.remove(child)
                changes += 1

    if changes:
        return serialize_xml(root, data), changes
    return data, 0


def anonymize_identity_attributes(
    name: str, data: bytes, clear_all_personal: bool
) -> tuple[bytes, int]:
    if not name.startswith("word/") or not is_xml_part(name) or name.endswith(".rels"):
        return data, 0
    try:
        root = parse_xml(data)
    except ET.ParseError:
        return data, 0
    changes = 0
    for element in root.iter():
        for attr_name, value in list(element.attrib.items()):
            if local_name(attr_name) not in IDENTITY_ATTRS:
                continue
            if clear_all_personal or AI_PATTERN.search(value):
                element.attrib[attr_name] = "Anonymous"
                changes += 1
    if changes:
        return serialize_xml(root, data), changes
    return data, 0


def source_part_for_rels(rels_name: str) -> str | None:
    path = PurePosixPath(rels_name)
    if path.name == ".rels" and str(path.parent) == "_rels":
        return None
    if path.parent.name != "_rels" or not path.name.endswith(".rels"):
        return None
    source_name = path.name[: -len(".rels")]
    return str(path.parent.parent / source_name)


def remove_ai_hyperlink_relationships(
    parts: dict[str, bytes],
) -> tuple[dict[str, bytes], int]:
    changed = dict(parts)
    total_changes = 0
    for rels_name, data in list(parts.items()):
        if not rels_name.endswith(".rels"):
            continue
        try:
            rel_root = parse_xml(data)
        except ET.ParseError:
            continue
        removed_ids: set[str] = set()
        for relationship in list(rel_root):
            if relationship.tag != REL_TAG:
                continue
            rel_type = relationship.attrib.get("Type", "")
            target = relationship.attrib.get("Target", "")
            if rel_type.endswith("/hyperlink") and AI_PATTERN.search(target):
                rel_id = relationship.attrib.get("Id")
                if rel_id:
                    removed_ids.add(rel_id)
                rel_root.remove(relationship)
                total_changes += 1
        if not removed_ids:
            continue
        changed[rels_name] = serialize_xml(rel_root, data)
        source_name = source_part_for_rels(rels_name)
        if not source_name or source_name not in changed:
            continue
        source_data = changed[source_name]
        try:
            source_root = parse_xml(source_data)
        except ET.ParseError:
            continue
        source_changes = 0
        parent_map = {child: parent for parent in source_root.iter() for child in parent}
        for element in list(source_root.iter()):
            matching_attrs = [
                attr
                for attr, value in element.attrib.items()
                if attr == OFFICE_REL_ID and value in removed_ids
            ]
            if not matching_attrs:
                continue
            if local_name(element.tag) == "hyperlink" and element in parent_map:
                parent = parent_map[element]
                index = list(parent).index(element)
                parent.remove(element)
                for child in list(element):
                    parent.insert(index, child)
                    index += 1
                source_changes += 1
            else:
                for attr in matching_attrs:
                    del element.attrib[attr]
                    source_changes += 1
        if source_changes:
            changed[source_name] = serialize_xml(source_root, source_data)
            total_changes += source_changes
    return changed, total_changes


def validate_package(parts: dict[str, bytes]) -> list[str]:
    errors: list[str] = []
    required = {"[Content_Types].xml", "_rels/.rels"}
    missing = sorted(required - set(parts))
    if missing:
        errors.append(f"missing required parts: {', '.join(missing)}")
    for name, data in parts.items():
        if not is_xml_part(name):
            continue
        try:
            parse_xml(data)
        except ET.ParseError as exc:
            errors.append(f"invalid XML in {name}: {exc}")
    return errors


def write_package(source: Path, output: Path, parts: dict[str, bytes]) -> None:
    if source.resolve() == output.resolve():
        raise ValueError("output must differ from input; the original is never overwritten")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source, "r") as src, zipfile.ZipFile(
        output, "w", allowZip64=True
    ) as dst:
        dst.comment = b""
        for info in src.infolist():
            new_info = copy(info)
            if info.is_dir():
                dst.writestr(new_info, b"")
            else:
                dst.writestr(new_info, parts[info.filename])


def load_parts(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path, "r") as archive:
        return {
            info.filename: archive.read(info.filename)
            for info in archive.infolist()
            if not info.is_dir()
        }


def print_findings(findings: Iterable[dict[str, str]], as_json: bool) -> None:
    items = list(findings)
    if as_json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return
    if not items:
        print("No ChatGPT/OpenAI indicators found.")
        return
    print(f"Found {len(items)} indicator(s):")
    for item in items:
        print(f"- [{item['classification']}] {item['part']}: {item['match']}")
        print(f"  {item['context'][:300]}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan or sanitize ChatGPT/OpenAI metadata in a DOCX file."
    )
    parser.add_argument("input", type=Path, help="source .docx file")
    parser.add_argument("--scan", action="store_true", help="scan only; do not write output")
    parser.add_argument("--output", type=Path, help="sanitized output .docx")
    parser.add_argument(
        "--remove-ai-hyperlinks",
        action="store_true",
        help="remove matching external hyperlink targets while preserving display text",
    )
    parser.add_argument(
        "--clear-all-personal",
        action="store_true",
        help="clear standard creator/company fields and all custom properties",
    )
    parser.add_argument("--json", action="store_true", help="print findings as JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.input
    if source.suffix.lower() != ".docx":
        print("error: input must be a .docx file", file=sys.stderr)
        return 2
    if not source.is_file():
        print(f"error: file not found: {source}", file=sys.stderr)
        return 2
    if not zipfile.is_zipfile(source):
        print("error: input is not a valid DOCX/ZIP package", file=sys.stderr)
        return 2

    before = scan_package(source)
    if args.scan or args.output is None:
        print_findings(before, args.json)
        return 0

    parts = load_parts(source)
    changes = 0
    for name, data in list(parts.items()):
        updated, count = clear_matching_properties(name, data, args.clear_all_personal)
        updated, identity_count = anonymize_identity_attributes(
            name, updated, args.clear_all_personal
        )
        parts[name] = updated
        changes += count + identity_count

    if args.remove_ai_hyperlinks:
        parts, hyperlink_changes = remove_ai_hyperlink_relationships(parts)
        changes += hyperlink_changes

    errors = validate_package(parts)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    try:
        write_package(source, args.output, parts)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    after = scan_package(args.output)
    if args.json:
        print(
            json.dumps(
                {
                    "input": str(source),
                    "output": str(args.output),
                    "changes": changes,
                    "before": before,
                    "remaining": after,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"Wrote: {args.output}")
        print(f"Applied {changes} XML metadata/relationship change(s).")
        print(f"Indicators before: {len(before)}; remaining: {len(after)}")
        if after:
            print("Remaining indicators require review (often visible content or custom XML):")
            print_findings(after, False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
