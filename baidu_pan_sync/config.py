from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from pathlib import PureWindowsPath
from typing import Iterable
import re
from urllib.parse import parse_qs, urlsplit, urlunsplit


def normalize_share_path(path: str) -> str:
    normalized = "/" + path.replace("\\", "/").strip("/")
    return "/" if normalized == "/" else normalized


def split_relative_to_prefix(path: str, prefix: str) -> str:
    path = normalize_share_path(path)
    prefix = normalize_share_path(prefix)
    if prefix == "/":
        return path.strip("/")
    if path == prefix:
        return ""
    return path[len(prefix) :].strip("/")


@dataclass(frozen=True)
class MappingRule:
    share_path: str
    local_dir: PureWindowsPath

    def __post_init__(self) -> None:
        object.__setattr__(self, "share_path", normalize_share_path(self.share_path))

    def matches(self, share_path: str) -> bool:
        path = normalize_share_path(share_path)
        if self.share_path == "/":
            return True
        return path == self.share_path or path.startswith(f"{self.share_path}/")


@dataclass(frozen=True)
class LocalResolution:
    matched_share_path: str
    local_path: PureWindowsPath


@dataclass(frozen=True)
class Subscription:
    id: str
    url: str
    passcode: str
    remote_transfer_root: str
    mappings: list[MappingRule]
    baseline_before: int | None = None

    def resolve_local_path(self, share_path: str) -> LocalResolution:
        matched = longest_prefix_match(share_path, self.mappings)
        if matched is None:
            raise ValueError(f"No mapping matched {share_path!r} for subscription {self.id!r}")

        suffix = split_relative_to_prefix(share_path, matched.share_path)
        local_path = matched.local_dir if suffix == "" else matched.local_dir / PureWindowsPath(suffix)
        return LocalResolution(matched_share_path=matched.share_path, local_path=local_path)


@dataclass(frozen=True)
class AppConfig:
    state_db: Path
    subscriptions: list[Subscription]

    def resolve_state_db(self, base_dir: Path) -> Path:
        if self.state_db.is_absolute():
            return self.state_db
        return base_dir / self.state_db

    def subscription_by_id(self, subscription_id: str) -> Subscription:
        for subscription in self.subscriptions:
            if subscription.id == subscription_id:
                return subscription
        raise KeyError(f"subscription {subscription_id!r} is not configured")


def longest_prefix_match(share_path: str, mappings: Iterable[MappingRule]) -> MappingRule | None:
    matches = [mapping for mapping in mappings if mapping.matches(share_path)]
    if not matches:
        return None
    return max(matches, key=lambda mapping: len(mapping.share_path.strip("/").split("/")))


def load_config(path: Path) -> AppConfig:
    data = parse_simple_yaml(path.read_text(encoding="utf-8"))
    subscriptions = [
        subscription_from_config_item(item)
        for item in data["subscriptions"]
        if is_enabled(item)
    ]
    return AppConfig(state_db=Path(data["state_db"]), subscriptions=subscriptions)


def subscription_from_config_item(item: dict[str, object]) -> Subscription:
    url, passcode = share_credentials(item)
    validate_share_url(url)
    return Subscription(
        id=item["id"],
        url=url,
        passcode=passcode,
        remote_transfer_root=item["remote_transfer_root"],
        mappings=[
            MappingRule(
                share_path=mapping["share_path"],
                local_dir=PureWindowsPath(mapping["local_dir"]),
            )
            for mapping in item["mappings"]
        ],
        baseline_before=parse_baseline_before(item.get("baseline_before")),
    )


def share_credentials(item: dict[str, object]) -> tuple[str, str]:
    if "share_url" in item:
        url, embedded_passcode = split_share_url(str(item["share_url"]))
        return url, str(item.get("passcode") or embedded_passcode)
    return str(item["url"]), str(item["passcode"])


def is_enabled(item: dict[str, object]) -> bool:
    return str(item.get("enabled", "true")).lower() not in {"false", "0", "no"}


def validate_share_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.netloc != "pan.baidu.com":
        raise ValueError(f"unsupported Baidu share URL: {url}")
    path = parsed.path.rstrip("/")
    if path.endswith("/share/init") and parse_qs(parsed.query).get("surl"):
        return
    if path.startswith("/s/1") and len(path.split("/s/", 1)[1]) > 1:
        return
    raise ValueError(f"unsupported Baidu share URL: {url}")


def split_share_url(share_url: str) -> tuple[str, str]:
    parsed = urlsplit(share_url)
    query = parse_qs(parsed.query)
    passcode = query.get("pwd", [""])[0]
    clean_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return clean_url, passcode


def parse_simple_yaml(text: str) -> dict[str, object]:
    lines = [line.rstrip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    result: dict[str, object] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("state_db:"):
            result["state_db"] = scalar(line.split(":", 1)[1].strip())
            index += 1
            continue
        if line == "subscriptions:":
            subscriptions, index = parse_subscriptions(lines, index + 1)
            result["subscriptions"] = subscriptions
            continue
        index += 1
    if "state_db" not in result or "subscriptions" not in result:
        raise ValueError("config must define state_db and subscriptions")
    return result


def parse_subscriptions(lines: list[str], index: int) -> tuple[list[dict[str, object]], int]:
    subscriptions: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    while index < len(lines):
        line = lines[index]
        if line.startswith("  - "):
            current = {}
            subscriptions.append(current)
            key, value = parse_key_value(line[4:])
            current[key] = value
            index += 1
            continue
        if line.startswith("    ") and current is not None:
            stripped = line[4:]
            if stripped == "mappings:":
                mappings, index = parse_mappings(lines, index + 1)
                current["mappings"] = mappings
                continue
            key, value = parse_key_value(stripped)
            current[key] = value
            index += 1
            continue
        break
    return subscriptions, index


def parse_mappings(lines: list[str], index: int) -> tuple[list[dict[str, str]], int]:
    mappings: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    while index < len(lines):
        line = lines[index]
        if line.startswith("      - "):
            current = {}
            mappings.append(current)
            key, value = parse_key_value(line[8:])
            current[key] = value
            index += 1
            continue
        if line.startswith("        ") and current is not None:
            key, value = parse_key_value(line[8:])
            current[key] = value
            index += 1
            continue
        break
    return mappings, index


def parse_key_value(text: str) -> tuple[str, str]:
    key, value = text.split(":", 1)
    return key.strip(), scalar(value.strip())


def scalar(value: str) -> str:
    return re.sub(r"^['\"]|['\"]$", "", value.strip())


def parse_baseline_before(value: object | None) -> int | None:
    if value in (None, ""):
        return None
    date = datetime.strptime(str(value), "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=8)))
    return int(date.timestamp())
