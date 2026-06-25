from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from typing import Sequence

from baidu_pan_sync.baidupcs import BaiduPcsGo
from baidu_pan_sync.baidu_share import BaiduShareClient
from baidu_pan_sync.config import load_config
from baidu_pan_sync.discover import manifest_from_share_listing
from baidu_pan_sync.ledger import SyncLedger
from baidu_pan_sync.models import ShareFile, SyncJob
from baidu_pan_sync.sync import SyncExecutor


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="baidu-pan-sync")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="Plan incremental sync jobs from a share manifest")
    plan_parser.add_argument("--config", required=True)
    plan_parser.add_argument("--manifest", required=True)
    plan_parser.add_argument("--output", required=True)

    manifest_parser = subparsers.add_parser(
        "manifest-from-listing",
        help="Convert a share listing JSON file into the standard sync manifest",
    )
    manifest_parser.add_argument("--subscription-id", required=True)
    manifest_parser.add_argument("--listing", required=True)
    manifest_parser.add_argument("--output", required=True)

    run_parser = subparsers.add_parser("run-planned", help="Run pending jobs already recorded in the ledger")
    run_parser.add_argument("--config", required=True)
    run_parser.add_argument("--payload-root", required=True)
    run_parser.add_argument("--output", required=True)

    baidupcs_parser = subparsers.add_parser("run-baidupcs", help="Run pending jobs with BaiduPCS-Go")
    baidupcs_parser.add_argument("--config", required=True)
    baidupcs_parser.add_argument("--baidupcs-bin", required=True)
    baidupcs_parser.add_argument("--baidupcs-config-dir", required=True)
    baidupcs_parser.add_argument("--output", required=True)

    transfer_parser = subparsers.add_parser("transfer-baidupcs", help="Transfer a configured share into Baidu Netdisk")
    transfer_parser.add_argument("--config", required=True)
    transfer_parser.add_argument("--subscription-id", required=True)
    transfer_parser.add_argument("--baidupcs-bin", required=True)
    transfer_parser.add_argument("--baidupcs-config-dir", required=True)
    transfer_parser.add_argument("--output", required=True)

    plan_transfer_parser = subparsers.add_parser(
        "plan-and-transfer-baidupcs",
        help="Plan jobs from a manifest and transfer only when new work exists",
    )
    plan_transfer_parser.add_argument("--config", required=True)
    plan_transfer_parser.add_argument("--manifest", required=True)
    plan_transfer_parser.add_argument("--subscription-id", required=True)
    plan_transfer_parser.add_argument("--baidupcs-bin", required=True)
    plan_transfer_parser.add_argument("--baidupcs-config-dir", required=True)
    plan_transfer_parser.add_argument("--output", required=True)

    sync_baidu_parser = subparsers.add_parser(
        "sync-baidu-share",
        help="Discover Baidu share files, selectively transfer new files, then download pending jobs",
    )
    sync_baidu_parser.add_argument("--config", required=True)
    sync_baidu_parser.add_argument("--cookie-file", required=True)
    sync_baidu_parser.add_argument("--share-sekeys-file")
    sync_baidu_parser.add_argument("--baidupcs-bin", required=True)
    sync_baidu_parser.add_argument("--baidupcs-config-dir", required=True)
    sync_baidu_parser.add_argument("--allow-full-transfer-fallback", action="store_true")
    sync_baidu_parser.add_argument("--output", required=True)

    args = parser.parse_args(argv)
    if args.command == "manifest-from-listing":
        return run_manifest_from_listing(Path(args.listing), args.subscription_id, Path(args.output))
    if args.command == "plan":
        return run_plan(Path(args.config), Path(args.manifest), Path(args.output))
    if args.command == "run-planned":
        return run_planned(Path(args.config), Path(args.payload_root), Path(args.output))
    if args.command == "run-baidupcs":
        return run_baidupcs(
            Path(args.config),
            Path(args.baidupcs_bin),
            Path(args.baidupcs_config_dir),
            Path(args.output),
        )
    if args.command == "transfer-baidupcs":
        return run_transfer_baidupcs(
            Path(args.config),
            args.subscription_id,
            Path(args.baidupcs_bin),
            Path(args.baidupcs_config_dir),
            Path(args.output),
        )
    if args.command == "plan-and-transfer-baidupcs":
        return run_plan_and_transfer_baidupcs(
            Path(args.config),
            Path(args.manifest),
            args.subscription_id,
            Path(args.baidupcs_bin),
            Path(args.baidupcs_config_dir),
            Path(args.output),
        )
    if args.command == "sync-baidu-share":
        return run_sync_baidu_share(
            Path(args.config),
            Path(args.cookie_file),
            Path(args.share_sekeys_file) if args.share_sekeys_file else None,
            Path(args.baidupcs_bin),
            Path(args.baidupcs_config_dir),
            Path(args.output),
            args.allow_full_transfer_fallback,
        )
    raise AssertionError(f"unknown command {args.command}")


def run_plan(config_path: Path, manifest_path: Path, output_path: Path) -> int:
    jobs = plan_jobs(config_path, manifest_path).jobs
    output_path.write_text(
        json.dumps({"jobs": [job_to_dict(job) for job in jobs]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


def plan_jobs(config_path: Path, manifest_path: Path) -> "PlanResult":
    app_config = load_config(config_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    state_db = app_config.resolve_state_db(config_path.parent)

    new_jobs: list[SyncJob] = []
    with SyncLedger.open(str(state_db)) as ledger:
        run_id = ledger.start_run()
        for item in manifest:
            share_file = ShareFile(
                subscription_id=item["subscription_id"],
                share_path=item["share_path"],
                size=int(item["size"]),
                mtime=item.get("mtime"),
                md5=item.get("md5"),
                fs_id=item.get("fs_id"),
            )
            subscription = app_config.subscription_by_id(share_file.subscription_id)
            resolution = subscription.resolve_local_path(share_file.share_path)
            job = ledger.schedule_if_needed(
                run_id,
                share_file,
                resolution,
                subscription.remote_transfer_root,
            )
            if job is not None:
                new_jobs.append(job)
        created_jobs = ledger.list_jobs_created_in_run(run_id)
    return PlanResult(jobs=new_jobs, created_jobs=created_jobs)


def run_manifest_from_listing(listing_path: Path, subscription_id: str, output_path: Path) -> int:
    listing = json.loads(listing_path.read_text(encoding="utf-8"))
    manifest = manifest_from_share_listing(subscription_id, listing)
    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def job_to_dict(job: SyncJob) -> dict[str, str | int]:
    return {
        "id": job.id,
        "subscription_id": job.subscription_id,
        "source_share_path": job.source_share_path,
        "matched_mapping": job.matched_mapping,
        "remote_transfer_path": job.remote_transfer_path,
        "local_path": job.local_path,
        "status": job.status,
        "fingerprint": job.fingerprint,
    }


def run_planned(config_path: Path, payload_root: Path, output_path: Path) -> int:
    return run_pending_jobs(config_path, LocalManifestDownloader(payload_root), output_path)


def run_baidupcs(config_path: Path, baidupcs_bin: Path, baidupcs_config_dir: Path, output_path: Path) -> int:
    return run_pending_jobs(config_path, BaiduPcsGo(baidupcs_bin, baidupcs_config_dir), output_path)


def run_transfer_baidupcs(
    config_path: Path,
    subscription_id: str,
    baidupcs_bin: Path,
    baidupcs_config_dir: Path,
    output_path: Path,
) -> int:
    app_config = load_config(config_path)
    subscription = app_config.subscription_by_id(subscription_id)
    pcs = BaiduPcsGo(baidupcs_bin, baidupcs_config_dir)
    pcs.transfer_share(subscription.url, subscription.passcode, subscription.remote_transfer_root)
    output_path.write_text(
        json.dumps({"transferred": [subscription.id]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


def run_plan_and_transfer_baidupcs(
    config_path: Path,
    manifest_path: Path,
    subscription_id: str,
    baidupcs_bin: Path,
    baidupcs_config_dir: Path,
    output_path: Path,
) -> int:
    plan_result = plan_jobs(config_path, manifest_path)
    subscription_jobs = [job for job in plan_result.created_jobs if job.subscription_id == subscription_id]
    transferred = False
    if subscription_jobs:
        app_config = load_config(config_path)
        subscription = app_config.subscription_by_id(subscription_id)
        BaiduPcsGo(baidupcs_bin, baidupcs_config_dir).transfer_share(
            subscription.url,
            subscription.passcode,
            subscription.remote_transfer_root,
        )
        transferred = True

    output_path.write_text(
        json.dumps(
            {
                "subscription_id": subscription_id,
                "new_jobs": len(subscription_jobs),
                "transferred": transferred,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


def load_share_sekeys(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("share sekeys file must contain a JSON object")
    return {str(key): str(value) for key, value in data.items() if value}


def save_share_sekeys(path: Path | None, sekeys: dict[str, str]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {key: value for key, value in sorted(sekeys.items()) if value}
    path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")


class PlanResult:
    def __init__(self, jobs: list[SyncJob], created_jobs: list[SyncJob]) -> None:
        self.jobs = jobs
        self.created_jobs = created_jobs


def run_sync_baidu_share(
    config_path: Path,
    cookie_file: Path,
    share_sekeys_file: Path | None,
    baidupcs_bin: Path,
    baidupcs_config_dir: Path,
    output_path: Path,
    allow_full_transfer_fallback: bool = False,
) -> int:
    app_config = load_config(config_path)
    share_client = BaiduShareClient(
        cookie_file.read_text(encoding="utf-8-sig"),
        sekeys=load_share_sekeys(share_sekeys_file),
    )
    pcs = BaiduPcsGo(baidupcs_bin, baidupcs_config_dir)
    state_db = app_config.resolve_state_db(config_path.parent)
    share_files_by_fingerprint: dict[tuple[str, str], ShareFile] = {}
    fallback_full_transfers: list[str] = []
    baseline_verified = 0

    with SyncLedger.open(str(state_db)) as ledger:
        run_id = ledger.start_run()
        for subscription in app_config.subscriptions:
            try:
                manifest = manifest_from_share_listing(
                    subscription.id,
                    share_client.list_share(subscription.url, subscription.passcode),
                )
            except RuntimeError:
                if not allow_full_transfer_fallback:
                    raise
                pcs.transfer_share(subscription.url, subscription.passcode, subscription.remote_transfer_root)
                fallback_full_transfers.append(subscription.id)
                continue
            for item in manifest:
                share_file = ShareFile(
                    subscription_id=item["subscription_id"],
                    share_path=item["share_path"],
                    size=int(item["size"]),
                    mtime=item.get("mtime"),
                    md5=item.get("md5"),
                    fs_id=item.get("fs_id"),
                )
                resolution = subscription.resolve_local_path(share_file.share_path)
                if is_before_baseline(share_file, subscription.baseline_before):
                    job = ledger.schedule_if_needed(
                        run_id,
                        share_file,
                        resolution,
                        subscription.remote_transfer_root,
                    )
                    if job is not None:
                        ledger.mark_job_verified(job.id, bytes_downloaded=share_file.size)
                        baseline_verified += 1
                    continue
                share_files_by_fingerprint[(share_file.subscription_id, share_file.fingerprint)] = share_file
                ledger.schedule_if_needed(
                    run_id,
                    share_file,
                    resolution,
                    subscription.remote_transfer_root,
                )

        created_jobs = [
            job
            for job in ledger.list_jobs_created_in_run(run_id)
            if (job.subscription_id, job.fingerprint) in share_files_by_fingerprint
        ]

    transferred = 0
    for subscription in app_config.subscriptions:
        fs_ids = [
            fs_id
            for job in created_jobs
            if job.subscription_id == subscription.id
            for fs_id in [share_files_by_fingerprint[(job.subscription_id, job.fingerprint)].fs_id]
            if fs_id
        ]
        missing_fs_id = len(fs_ids) != len([job for job in created_jobs if job.subscription_id == subscription.id])
        if missing_fs_id:
            raise ValueError(f"new share files for subscription {subscription.id!r} must include fs_id")
        if fs_ids:
            pcs.ensure_remote_dir(subscription.remote_transfer_root)
            share_client.transfer_files(
                subscription.url,
                subscription.passcode,
                fs_ids,
                subscription.remote_transfer_root,
            )
            transferred += len(fs_ids)

    verified, failed = execute_pending_jobs(config_path, pcs)
    save_share_sekeys(share_sekeys_file, share_client.sekeys)
    output_path.write_text(
        json.dumps(
            {
                "new_jobs": len(created_jobs),
                "transferred": transferred,
                "baseline_verified": baseline_verified,
                "fallback_full_transfers": fallback_full_transfers,
                "verified": verified,
                "failed": failed,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0 if failed == 0 else 1


def is_before_baseline(share_file: ShareFile, baseline_before: int | None) -> bool:
    if baseline_before is None or share_file.mtime is None:
        return False
    return int(share_file.mtime) < baseline_before


def run_pending_jobs(config_path: Path, downloader: object, output_path: Path) -> int:
    verified, failed = execute_pending_jobs(config_path, downloader)
    output_path.write_text(
        json.dumps({"verified": verified, "failed": failed}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0 if failed == 0 else 1


def execute_pending_jobs(config_path: Path, downloader: object) -> tuple[int, int]:
    app_config = load_config(config_path)
    state_db = app_config.resolve_state_db(config_path.parent)
    verified = 0
    failed = 0
    with SyncLedger.open(str(state_db)) as ledger:
        executor = SyncExecutor(ledger, downloader)
        for job in ledger.list_pending_jobs():
            try:
                result = executor.run_job(job)
                if result.status == "VERIFIED":
                    verified += 1
            except Exception:
                failed += 1
    return verified, failed


class LocalManifestDownloader:
    def __init__(self, payload_root: Path) -> None:
        self.payload_root = payload_root

    def download_file(self, remote_path: str, part_path: Path) -> None:
        source = self.payload_root / remote_path.strip("/")
        part_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, part_path)


if __name__ == "__main__":
    raise SystemExit(main())
