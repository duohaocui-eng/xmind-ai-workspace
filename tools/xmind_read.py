from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from xmind_core import (
    XMindError,
    build_tree,
    document_summary,
    file_sha256,
    get_sheets,
    iter_topics,
    load_package,
    normalize_topic,
    resolve_sheet,
    resolve_topic,
    sheet_root,
)


def parse_selector(value: str) -> Any:
    value = value.strip()
    if not value:
        return None
    if value.startswith("{"):
        return json.loads(value)
    return value


def tree_lines(topic: dict[str, Any], prefix: str = "", last: bool = True, kind: str = "root", is_root: bool = True) -> list[str]:
    label = str(topic.get("title") or "")
    tid = topic.get("id")
    pos = topic.get("position")
    marker = ""
    if kind == "detached":
        marker = " [free]"
    if pos:
        marker += f" @({pos.get('x')},{pos.get('y')})"

    head = label if is_root else prefix + ("└─ " if last else "├─ ") + label
    if tid:
        head += f"  <{tid}>"
    head += marker
    lines = [head]

    children = topic.get("children") or {}
    flat: list[tuple[str, dict[str, Any]]] = []
    if isinstance(children, dict):
        for bucket, arr in children.items():
            if isinstance(arr, list):
                for child in arr:
                    if isinstance(child, dict):
                        flat.append((bucket, child))

    next_prefix = "" if is_root else prefix + ("   " if last else "│  ")
    for i, (bucket, child) in enumerate(flat):
        child_lines = tree_lines(child, next_prefix, i == len(flat) - 1, bucket, False)
        if bucket == "detached" and child_lines:
            child_lines[0] += " [detached]"
        lines.extend(child_lines)
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read XMind .xmind files as structured JSON or a human-readable tree."
    )
    parser.add_argument("file", help="Path to .xmind file")
    parser.add_argument(
        "--format",
        choices=["summary", "json", "tree"],
        default="summary",
        help="Output format (default: summary)",
    )
    parser.add_argument("--sheet", help="Sheet ID/title, or JSON selector")
    parser.add_argument("--topic", help="Topic ID/title, or JSON selector")
    parser.add_argument("--find", help="Substring search in topic titles")
    parser.add_argument("--max-depth", type=int, default=None, help="Limit JSON/tree depth")
    parser.add_argument("--include-keys", action="store_true", help="Include raw topic field names in JSON search/topic results")
    args = parser.parse_args()

    try:
        entries, content = load_package(args.file)
        sheet_selector = parse_selector(args.sheet) if args.sheet else None

        if args.topic:
            selector = parse_selector(args.topic)
            if isinstance(selector, str):
                # Prefer exact ID; if no match, retry as exact title.
                try:
                    ref = resolve_topic(content, {"id": selector}, default_sheet=sheet_selector)
                except XMindError:
                    ref = resolve_topic(content, {"title": selector}, default_sheet=sheet_selector)
            else:
                ref = resolve_topic(content, selector, default_sheet=sheet_selector)
            print(json.dumps(normalize_topic(ref, include_keys=args.include_keys), ensure_ascii=False, indent=2))
            return 0

        if args.find is not None:
            q = args.find.casefold()
            sheets = [resolve_sheet(content, sheet_selector)] if sheet_selector is not None else get_sheets(content)
            matches = []
            for sheet in sheets:
                for ref in iter_topics(sheet):
                    title = str(ref.node.get("title") or "")
                    if q in title.casefold():
                        matches.append(normalize_topic(ref, include_keys=args.include_keys))
            print(json.dumps({"query": args.find, "count": len(matches), "matches": matches}, ensure_ascii=False, indent=2))
            return 0

        if args.format == "summary":
            summary = document_summary(content)
            summary["file"] = str(Path(args.file))
            summary["file_sha256"] = file_sha256(args.file)
            summary["zip_entries"] = [
                {"name": e.info.filename, "size": len(e.data), "compression": e.info.compress_type}
                for e in entries
            ]
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0

        sheets = [resolve_sheet(content, sheet_selector)] if sheet_selector is not None else get_sheets(content)

        if args.format == "json":
            payload = {
                "file": str(Path(args.file)),
                "file_sha256": file_sha256(args.file),
                "sheets": [
                    {
                        "id": sheet.get("id"),
                        "title": sheet.get("title"),
                        "root": build_tree(sheet_root(sheet), max_depth=args.max_depth),
                    }
                    for sheet in sheets
                ],
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        for si, sheet in enumerate(sheets):
            if si:
                print()
            print(f"# {sheet.get('title')}  <{sheet.get('id')}>")
            root_tree = build_tree(sheet_root(sheet), max_depth=args.max_depth)
            for line in tree_lines(root_tree):
                print(line)
        return 0
    except (XMindError, json.JSONDecodeError, OSError) as e:
        parser.error(str(e))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

