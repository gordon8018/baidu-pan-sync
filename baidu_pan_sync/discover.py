from __future__ import annotations

from typing import Any


def manifest_from_share_listing(subscription_id: str, listing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for item in listing:
        if is_directory(item):
            continue
        share_path = item_share_path(item)
        if share_path is None:
            raise ValueError(f"share path is required for subscription {subscription_id!r}")
        manifest.append(
            {
                "subscription_id": subscription_id,
                "share_path": share_path,
                "size": int(item.get("size", 0)),
                "mtime": item.get("server_mtime") or item.get("mtime"),
                "md5": item.get("md5"),
                "fs_id": str(item["fs_id"]) if "fs_id" in item else None,
            }
        )
    return manifest


def is_directory(item: dict[str, Any]) -> bool:
    if "isdir" in item:
        return bool(item["isdir"])
    if "is_dir" in item:
        return bool(item["is_dir"])
    return False


def item_share_path(item: dict[str, Any]) -> str | None:
    if item.get("path"):
        return normalize_share_path(str(item["path"]))
    filename = item.get("server_filename") or item.get("filename") or item.get("name")
    parent = item.get("parent_path") or item.get("parent") or item.get("dir")
    if filename and parent:
        return normalize_share_path(f"{parent}/{filename}")
    return None


def normalize_share_path(path: str) -> str:
    normalized = "/" + path.replace("\\", "/").strip("/")
    return "/" if normalized == "/" else normalized
