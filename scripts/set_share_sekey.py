from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse, unquote

from baidu_pan_sync.config import load_config
from baidu_pan_sync.baidu_share import feature_from_share_url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Store a Baidu share sekey for one configured subscription.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--sekeys-file", required=True)
    parser.add_argument("--sekey", required=True, help="Raw BDCLND value or a copied /share/list URL containing sekey=")
    args = parser.parse_args(argv)

    config = load_config(Path(args.config))
    subscription = config.subscription_by_id(args.subscription_id)
    feature = feature_from_share_url(subscription.url)
    sekey = extract_sekey(args.sekey)

    sekeys_path = Path(args.sekeys_file)
    sekeys: dict[str, str] = {}
    if sekeys_path.exists():
        sekeys = json.loads(sekeys_path.read_text(encoding="utf-8-sig"))
    sekeys[feature] = sekey
    sekeys_path.parent.mkdir(parents=True, exist_ok=True)
    sekeys_path.write_text(json.dumps(sekeys, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"subscription_id": args.subscription_id, "feature": feature, "saved": True}, ensure_ascii=False))
    return 0


def extract_sekey(value: str) -> str:
    parsed = urlparse(value)
    if parsed.query:
        for item in parsed.query.split("&"):
            if item.startswith("sekey="):
                return unquote(item.split("=", 1)[1])
    if value.startswith("BDCLND="):
        return value.split("=", 1)[1]
    if value.startswith("sekey="):
        return value.split("=", 1)[1]
    return value.strip()


if __name__ == "__main__":
    raise SystemExit(main())
