from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


class XMindError(RuntimeError):
    pass


@dataclass
class PackageEntry:
    info: zipfile.ZipInfo
    data: bytes


@dataclass
class TopicRef:
    sheet: dict[str, Any]
    node: dict[str, Any]
    parent: dict[str, Any] | None
    bucket_key: str | None
    bucket: list[dict[str, Any]] | None
    index: int | None
    kind: str


def new_id() -> str:
    return str(uuid.uuid4())


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_package(path: str | Path) -> tuple[list[PackageEntry], Any]:
    path = Path(path)
    if not path.exists():
        raise XMindError(f"file not found: {path}")
    try:
        with zipfile.ZipFile(path, "r") as z:
            entries = [PackageEntry(info, z.read(info.filename)) for info in z.infolist()]
    except zipfile.BadZipFile as e:
        raise XMindError(f"not a valid XMind/ZIP file: {path}") from e

    content_entry = next((e for e in entries if e.info.filename == "content.json"), None)
    if content_entry is None:
        raise XMindError("content.json not found in XMind package")
    try:
        content = json.loads(content_entry.data.decode("utf-8"))
    except Exception as e:
        raise XMindError("content.json is not valid UTF-8 JSON") from e
    return entries, content


def get_sheets(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, list):
        return content
    if isinstance(content, dict) and isinstance(content.get("sheets"), list):
        return content["sheets"]
    raise XMindError("unsupported content.json top-level structure")


def sheet_root(sheet: dict[str, Any]) -> dict[str, Any]:
    root = sheet.get("rootTopic") or sheet.get("root-topic")
    if not isinstance(root, dict):
        raise XMindError(f"sheet has no root topic: {sheet.get('title') or sheet.get('id')}")
    return root


def children_buckets(topic: dict[str, Any]) -> Iterable[tuple[str, list[dict[str, Any]]]]:
    children = topic.get("children")
    if not isinstance(children, dict):
        return
    for key, value in children.items():
        if isinstance(value, list):
            yield key, value


def iter_topics(sheet: dict[str, Any]) -> Iterable[TopicRef]:
    root = sheet_root(sheet)

    def walk(
        node: dict[str, Any],
        parent: dict[str, Any] | None,
        bucket_key: str | None,
        bucket: list[dict[str, Any]] | None,
        index: int | None,
        kind: str,
    ) -> Iterable[TopicRef]:
        yield TopicRef(sheet, node, parent, bucket_key, bucket, index, kind)
        for key, arr in children_buckets(node):
            for i, child in enumerate(arr):
                if isinstance(child, dict):
                    yield from walk(child, node, key, arr, i, key)

    yield from walk(root, None, None, None, None, "root")

    # Some XMind variants also store detached topics at sheet level.
    sheet_children = sheet.get("children")
    if isinstance(sheet_children, dict):
        detached = sheet_children.get("detached")
        if isinstance(detached, list):
            for i, child in enumerate(detached):
                if isinstance(child, dict):
                    yield from walk(child, None, "detached", detached, i, "detached")


def topic_path(ref: TopicRef) -> list[str]:
    target = ref.node.get("id")
    root = sheet_root(ref.sheet)
    path: list[str] = []

    def dfs(node: dict[str, Any]) -> bool:
        path.append(str(node.get("title") or ""))
        if node.get("id") == target:
            return True
        for _, arr in children_buckets(node):
            for child in arr:
                if isinstance(child, dict) and dfs(child):
                    return True
        path.pop()
        return False

    if dfs(root):
        return path
    return [str(ref.node.get("title") or "")]


def resolve_sheet(content: Any, selector: Any | None) -> dict[str, Any]:
    sheets = get_sheets(content)
    if selector is None:
        if len(sheets) != 1:
            raise XMindError("sheet selector required because file has multiple sheets")
        return sheets[0]

    if isinstance(selector, str):
        selector = {"id": selector} if any(s.get("id") == selector for s in sheets) else {"title": selector}
    if not isinstance(selector, dict):
        raise XMindError("sheet selector must be a string or object")

    candidates = sheets
    if selector.get("id") is not None:
        candidates = [s for s in candidates if s.get("id") == selector["id"]]
    if selector.get("title") is not None:
        candidates = [s for s in candidates if s.get("title") == selector["title"]]
    if len(candidates) != 1:
        raise XMindError(f"sheet selector matched {len(candidates)} sheets: {selector}")
    return candidates[0]


def resolve_topic(content: Any, selector: Any, *, default_sheet: Any | None = None) -> TopicRef:
    if isinstance(selector, str):
        selector = {"id": selector}
    if not isinstance(selector, dict):
        raise XMindError("topic selector must be a string ID or object")

    sheet_selector = selector.get("sheet", default_sheet)
    sheets = [resolve_sheet(content, sheet_selector)] if sheet_selector is not None else get_sheets(content)

    matches: list[TopicRef] = []
    for sheet in sheets:
        for ref in iter_topics(sheet):
            node = ref.node
            if selector.get("id") is not None and node.get("id") != selector["id"]:
                continue
            if selector.get("title") is not None and node.get("title") != selector["title"]:
                continue
            matches.append(ref)

    if len(matches) != 1:
        desc = {k: v for k, v in selector.items() if k != "sheet"}
        raise XMindError(f"topic selector matched {len(matches)} topics: {desc}")
    return matches[0]


def ensure_bucket(topic: dict[str, Any], key: str) -> list[dict[str, Any]]:
    children = topic.setdefault("children", {})
    if not isinstance(children, dict):
        raise XMindError("topic children is not an object")
    bucket = children.setdefault(key, [])
    if not isinstance(bucket, list):
        raise XMindError(f"topic children.{key} is not a list")
    return bucket


def remove_topic(ref: TopicRef) -> dict[str, Any]:
    if ref.parent is None and ref.bucket is None:
        raise XMindError("cannot remove a sheet root topic")
    if ref.bucket is None or ref.index is None:
        raise XMindError("topic is not removable from its current container")
    return ref.bucket.pop(ref.index)


def detach_bucket(sheet: dict[str, Any]) -> list[dict[str, Any]]:
    # Prefer root.children.detached; this works in modern XMind and is what
    # current validation used. Keep sheet-level detached readable for compatibility.
    return ensure_bucket(sheet_root(sheet), "detached")


def clone_theme_with_new_ids(theme: Any) -> Any:
    cloned = copy.deepcopy(theme)

    def walk(x: Any) -> None:
        if isinstance(x, list):
            for item in x:
                walk(item)
        elif isinstance(x, dict):
            for key, value in list(x.items()):
                if key == "id" and isinstance(value, str):
                    x[key] = new_id()
                else:
                    walk(value)

    walk(cloned)
    return cloned


def validate(content: Any) -> dict[str, Any]:
    sheets = get_sheets(content)
    if not sheets:
        raise XMindError("XMind must contain at least one sheet")

    sheet_ids: set[str] = set()
    topic_ids: set[str] = set()
    topic_count = 0
    detached_count = 0

    for sheet in sheets:
        sid = sheet.get("id")
        if not isinstance(sid, str) or not sid:
            raise XMindError("sheet missing non-empty string id")
        if sid in sheet_ids:
            raise XMindError(f"duplicate sheet id: {sid}")
        sheet_ids.add(sid)
        sheet_root(sheet)

        for ref in iter_topics(sheet):
            topic_count += 1
            tid = ref.node.get("id")
            if not isinstance(tid, str) or not tid:
                raise XMindError(f"topic missing non-empty string id in sheet {sheet.get('title')}")
            if tid in topic_ids:
                raise XMindError(f"duplicate topic id: {tid}")
            topic_ids.add(tid)
            if ref.kind == "detached":
                detached_count += 1
            pos = ref.node.get("position")
            if pos is not None:
                if not isinstance(pos, dict) or not isinstance(pos.get("x"), (int, float)) or not isinstance(pos.get("y"), (int, float)):
                    raise XMindError(f"invalid position for topic {tid}")

    return {
        "sheet_count": len(sheets),
        "topic_count": topic_count,
        "detached_count": detached_count,
    }


def package_payload_hashes(entries: list[PackageEntry], *, exclude: set[str] | None = None) -> dict[str, str]:
    exclude = exclude or set()
    return {
        e.info.filename: sha256_bytes(e.data)
        for e in entries
        if e.info.filename not in exclude
    }


def _copy_zipinfo(info: zipfile.ZipInfo) -> zipfile.ZipInfo:
    new = zipfile.ZipInfo(info.filename, date_time=info.date_time)
    new.compress_type = info.compress_type
    new.comment = info.comment
    new.extra = info.extra
    new.internal_attr = info.internal_attr
    new.external_attr = info.external_attr
    new.create_system = info.create_system
    new.create_version = info.create_version
    new.extract_version = info.extract_version
    new.flag_bits = info.flag_bits
    new.volume = info.volume
    return new


def write_package(
    path: str | Path,
    entries: list[PackageEntry],
    content: Any,
    *,
    output: str | Path | None = None,
) -> Path:
    source = Path(path)
    destination = Path(output) if output else source
    destination.parent.mkdir(parents=True, exist_ok=True)

    content_bytes = json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    temp_dir = destination.parent
    fd, temp_name = tempfile.mkstemp(prefix=destination.name + ".", suffix=".tmp", dir=temp_dir)
    os.close(fd)
    temp_path = Path(temp_name)

    try:
        with zipfile.ZipFile(temp_path, "w") as z:
            seen_content = False
            for entry in entries:
                info = _copy_zipinfo(entry.info)
                data = content_bytes if info.filename == "content.json" else entry.data
                if info.filename == "content.json":
                    seen_content = True
                z.writestr(info, data)
            if not seen_content:
                raise XMindError("content.json disappeared while writing")

        # Full post-write validation.
        new_entries, new_content = load_package(temp_path)
        validate(new_content)

        before = package_payload_hashes(entries, exclude={"content.json"})
        after = package_payload_hashes(new_entries, exclude={"content.json"})
        if before != after:
            changed = sorted(set(before) | set(after))
            changed = [name for name in changed if before.get(name) != after.get(name)]
            raise XMindError(f"non-content payload changed unexpectedly: {changed}")

        os.replace(temp_path, destination)
        return destination
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def normalize_topic(ref: TopicRef, *, include_keys: bool = False) -> dict[str, Any]:
    out = {
        "id": ref.node.get("id"),
        "title": ref.node.get("title"),
        "kind": ref.kind,
        "parent_id": ref.parent.get("id") if ref.parent else None,
        "position": ref.node.get("position"),
        "path": topic_path(ref),
    }
    if include_keys:
        out["keys"] = sorted(ref.node.keys())
    return out


def document_summary(content: Any) -> dict[str, Any]:
    sheets = get_sheets(content)
    validation = validate(content)
    return {
        **validation,
        "sheets": [
            {
                "id": s.get("id"),
                "title": s.get("title"),
                "root_id": sheet_root(s).get("id"),
                "root_title": sheet_root(s).get("title"),
                "topic_count": sum(1 for _ in iter_topics(s)),
            }
            for s in sheets
        ],
    }


def build_tree(topic: dict[str, Any], *, max_depth: int | None = None, depth: int = 0) -> dict[str, Any]:
    node = {
        "id": topic.get("id"),
        "title": topic.get("title"),
    }
    if topic.get("position") is not None:
        node["position"] = topic.get("position")
    if max_depth is not None and depth >= max_depth:
        return node

    children: dict[str, list[dict[str, Any]]] = {}
    for key, arr in children_buckets(topic):
        children[key] = [build_tree(child, max_depth=max_depth, depth=depth + 1) for child in arr if isinstance(child, dict)]
    if children:
        node["children"] = children
    return node

