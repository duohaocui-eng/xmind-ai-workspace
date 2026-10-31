from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from xmind_core import (
    XMindError,
    clone_theme_with_new_ids,
    detach_bucket,
    document_summary,
    ensure_bucket,
    file_sha256,
    get_sheets,
    load_package,
    new_id,
    remove_topic,
    resolve_sheet,
    resolve_topic,
    sheet_root,
    validate,
    write_package,
)


SUPPORTED_OPS = {
    "rename",
    "add",
    "delete",
    "move",
    "add_detached",
    "set_position",
    "add_sheet",
    "delete_sheet",
    "rename_sheet",
}


def _selector(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, dict)):
        return value
    raise XMindError(f"invalid selector: {value!r}")


def _topic_desc(ref: Any) -> dict[str, Any]:
    return {
        "id": ref.node.get("id"),
        "title": ref.node.get("title"),
        "sheet_id": ref.sheet.get("id"),
        "sheet_title": ref.sheet.get("title"),
        "parent_id": ref.parent.get("id") if ref.parent else None,
        "kind": ref.kind,
        "position": ref.node.get("position"),
    }


def _subtree_ids(node: dict[str, Any]) -> set[str]:
    ids: set[str] = set()

    def walk(n: dict[str, Any]) -> None:
        tid = n.get("id")
        if isinstance(tid, str):
            ids.add(tid)
        children = n.get("children")
        if isinstance(children, dict):
            for arr in children.values():
                if isinstance(arr, list):
                    for child in arr:
                        if isinstance(child, dict):
                            walk(child)

    walk(node)
    return ids


def apply_operation(content: Any, op: dict[str, Any]) -> dict[str, Any]:
    name = op.get("op")
    if name not in SUPPORTED_OPS:
        raise XMindError(f"unsupported operation: {name!r}")

    if name == "rename":
        ref = resolve_topic(content, _selector(op.get("target")), default_sheet=op.get("sheet"))
        before = _topic_desc(ref)
        title = op.get("title")
        if not isinstance(title, str):
            raise XMindError("rename requires string 'title'")
        ref.node["title"] = title
        ref.node.pop("titleUnedited", None)
        return {"op": name, "before": before, "after": _topic_desc(ref)}

    if name == "add":
        parent = resolve_topic(content, _selector(op.get("parent")), default_sheet=op.get("sheet"))
        title = op.get("title")
        if not isinstance(title, str):
            raise XMindError("add requires string 'title'")
        bucket_name = op.get("bucket", "attached")
        if not isinstance(bucket_name, str):
            raise XMindError("add 'bucket' must be a string")
        node: dict[str, Any] = {
            "id": op.get("id") or new_id(),
            "title": title,
        }
        if op.get("position") is not None:
            node["position"] = copy.deepcopy(op["position"])
        index = op.get("index")
        bucket = ensure_bucket(parent.node, bucket_name)
        if index is None:
            bucket.append(node)
            index = len(bucket) - 1
        else:
            if not isinstance(index, int) or index < 0 or index > len(bucket):
                raise XMindError("add 'index' must be within the target bucket")
            bucket.insert(index, node)
        ref = resolve_topic(content, {"id": node["id"]})
        return {"op": name, "parent": _topic_desc(parent), "created": _topic_desc(ref), "index": index}

    if name == "delete":
        ref = resolve_topic(content, _selector(op.get("target")), default_sheet=op.get("sheet"))
        before = _topic_desc(ref)
        removed = remove_topic(ref)
        return {"op": name, "deleted": before, "deleted_subtree_root": removed.get("id")}

    if name == "move":
        ref = resolve_topic(content, _selector(op.get("target")), default_sheet=op.get("sheet"))
        if ref.parent is None and ref.bucket is None:
            raise XMindError("cannot move a sheet root topic")
        new_parent = resolve_topic(content, _selector(op.get("new_parent")), default_sheet=op.get("new_sheet"))
        if new_parent.node.get("id") in _subtree_ids(ref.node):
            raise XMindError("cannot move a topic into its own subtree")

        before = _topic_desc(ref)
        node = remove_topic(ref)
        bucket_name = op.get("bucket", "attached")
        bucket = ensure_bucket(new_parent.node, bucket_name)
        index = op.get("index")
        if index is None:
            bucket.append(node)
            index = len(bucket) - 1
        else:
            if not isinstance(index, int) or index < 0 or index > len(bucket):
                raise XMindError("move 'index' must be within the target bucket")
            bucket.insert(index, node)
        after_ref = resolve_topic(content, {"id": node.get("id")})
        return {
            "op": name,
            "before": before,
            "new_parent": _topic_desc(new_parent),
            "after": _topic_desc(after_ref),
            "index": index,
        }

    if name == "add_detached":
        sheet = resolve_sheet(content, _selector(op.get("sheet")))
        title = op.get("title")
        if not isinstance(title, str):
            raise XMindError("add_detached requires string 'title'")
        position = op.get("position")
        if not isinstance(position, dict) or not isinstance(position.get("x"), (int, float)) or not isinstance(position.get("y"), (int, float)):
            raise XMindError("add_detached requires position {x, y}")
        node = {
            "id": op.get("id") or new_id(),
            "title": title,
            "position": {"x": position["x"], "y": position["y"]},
        }
        detach_bucket(sheet).append(node)
        ref = resolve_topic(content, {"id": node["id"]})
        return {"op": name, "created": _topic_desc(ref)}

    if name == "set_position":
        ref = resolve_topic(content, _selector(op.get("target")), default_sheet=op.get("sheet"))
        position = op.get("position")
        if not isinstance(position, dict) or not isinstance(position.get("x"), (int, float)) or not isinstance(position.get("y"), (int, float)):
            raise XMindError("set_position requires position {x, y}")
        before = _topic_desc(ref)
        ref.node["position"] = {"x": position["x"], "y": position["y"]}
        return {"op": name, "before": before, "after": _topic_desc(ref)}

    if name == "rename_sheet":
        sheet = resolve_sheet(content, _selector(op.get("sheet")))
        title = op.get("title")
        if not isinstance(title, str):
            raise XMindError("rename_sheet requires string 'title'")
        before = {"id": sheet.get("id"), "title": sheet.get("title")}
        sheet["title"] = title
        return {"op": name, "before": before, "after": {"id": sheet.get("id"), "title": sheet.get("title")}}

    if name == "add_sheet":
        sheets = get_sheets(content)
        template = resolve_sheet(content, _selector(op.get("template_sheet"))) if op.get("template_sheet") is not None else sheets[0]
        title = op.get("title")
        root_title = op.get("root_title", title)
        if not isinstance(title, str) or not isinstance(root_title, str):
            raise XMindError("add_sheet requires string 'title' and optional string 'root_title'")

        new_sheet = copy.deepcopy(template)
        new_sheet["id"] = op.get("id") or new_id()
        new_sheet["revisionId"] = new_id()
        new_sheet["title"] = title
        new_sheet.pop("children", None)
        new_sheet.pop("relationships", None)
        new_sheet["zones"] = []

        template_root = sheet_root(template)
        root_id = op.get("root_id") or new_id()
        new_root = {
            "id": root_id,
            "class": template_root.get("class", "topic"),
            "title": root_title,
            "structureClass": template_root.get("structureClass", "org.xmind.ui.map.clockwise"),
        }
        new_sheet["rootTopic"] = new_root
        new_sheet.pop("root-topic", None)
        new_sheet["arrangeableLayerOrder"] = [root_id]
        if new_sheet.get("theme") is not None:
            new_sheet["theme"] = clone_theme_with_new_ids(new_sheet["theme"])
        sheets.append(new_sheet)

        return {
            "op": name,
            "created": {
                "id": new_sheet["id"],
                "title": new_sheet["title"],
                "root_id": root_id,
                "root_title": root_title,
            },
        }

    if name == "delete_sheet":
        sheets = get_sheets(content)
        if len(sheets) <= 1:
            raise XMindError("cannot delete the last sheet")
        sheet = resolve_sheet(content, _selector(op.get("sheet")))
        idx = next(i for i, s in enumerate(sheets) if s is sheet)
        removed = sheets.pop(idx)
        return {"op": name, "deleted": {"id": removed.get("id"), "title": removed.get("title")}, "index": idx}

    raise XMindError(f"operation not implemented: {name}")


def load_request(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise XMindError("request must be a JSON object")
    return data


def load_ops(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("operations"), list):
        data = data["operations"]
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        raise XMindError("ops file must be a JSON array or an object with an 'operations' array")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely edit XMind .xmind files using explicit JSON operations."
    )
    parser.add_argument("file", nargs="?", help="Path to .xmind file")
    parser.add_argument("--ops", help="JSON operations file")
    parser.add_argument("--request", help="Request JSON containing file and operations")
    parser.add_argument("--output", help="Write to another .xmind instead of in-place")
    parser.add_argument("--dry-run", action="store_true", help="Apply and validate operations without writing")
    parser.add_argument("--report", help="Write JSON operation report to this path")
    parser.add_argument("--expect-sha256", help="Abort if input file SHA-256 differs")
    args = parser.parse_args()

    try:
        request: dict[str, Any] = {}
        if args.request:
            request = load_request(args.request)

        file_path = args.file or request.get("file")
        if not isinstance(file_path, str) or not file_path:
            raise XMindError("XMind file path is required")

        if args.ops:
            operations = load_ops(args.ops)
        else:
            operations = request.get("operations")
            if not isinstance(operations, list) or not all(isinstance(x, dict) for x in operations):
                raise XMindError("operations are required via --ops or --request")

        output = args.output or request.get("output")
        expected = args.expect_sha256 or request.get("expect_sha256")
        if expected is not None and file_sha256(file_path) != expected:
            raise XMindError("input SHA-256 did not match expect_sha256; refusing stale edit")

        entries, content = load_package(file_path)
        before = document_summary(content)
        input_sha = file_sha256(file_path)

        op_reports = []
        for i, op in enumerate(operations):
            try:
                op_reports.append(apply_operation(content, op))
            except Exception as e:
                raise XMindError(f"operation #{i + 1} failed ({op.get('op')}): {e}") from e

        after_validation = validate(content)
        after = document_summary(content)

        report = {
            "version": 1,
            "request_id": request.get("request_id"),
            "file": file_path,
            "output": output or file_path,
            "dry_run": args.dry_run,
            "input_sha256": input_sha,
            "before": before,
            "after": after,
            "validation": after_validation,
            "operations": op_reports,
        }

        if not args.dry_run:
            written = write_package(file_path, entries, content, output=output)
            report["written_sha256"] = file_sha256(written)

        report_path = args.report or request.get("report")
        if isinstance(report_path, str) and report_path:
            p = Path(report_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (XMindError, json.JSONDecodeError, OSError) as e:
        parser.error(str(e))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

