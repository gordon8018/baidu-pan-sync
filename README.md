# baidu-pan-sync

Incremental synchronizer for Baidu Netdisk share subscriptions.

This project keeps a SQLite ledger so daily runs remember which files were already
discovered, transferred, downloaded, and verified. A local file existing on disk is
not treated as success unless the ledger job is `VERIFIED`.

## Current scope

- Configure three or more Baidu share subscriptions.
- Accept either `url` + `passcode` or a full `share_url` like
  `https://pan.baidu.com/s/xxx?pwd=abcd`.
- Map different directories inside each share to different local directories.
- Compute stable file fingerprints from subscription id, share path, size, mtime,
  md5, or fs_id.
- Store sync runs, discovered files, and jobs in SQLite.
- Resume incomplete jobs instead of creating duplicates.
- Fail loudly when an upstream share path does not match a configured mapping.
- Discover real Baidu share files through the web share API.
- Transfer only newly discovered share `fs_id` values into the fixed remote
  staging directory.

The real Baidu Netdisk operations are split intentionally:

- `baidu_share.py` uses a cookie file and Baidu's web share endpoints to list
  share files and selectively transfer only new `fs_id` values.
- `baidupcs.py` uses BaiduPCS-Go to download transferred files from your own
  Baidu Netdisk staging directory.

Do not commit or print cookie files. Keep them outside version control.

## Example dry plan

Convert a share listing JSON file into the standard manifest format:

```powershell
python -m baidu_pan_sync.cli manifest-from-listing `
  --subscription-id source_a `
  --listing examples/share_listing.json `
  --output work/source_a.manifest.json
```

Then record resumable jobs in the SQLite ledger:

```powershell
python -m baidu_pan_sync.cli plan `
  --config config.example.yaml `
  --manifest work/source_a.manifest.json `
  --output work/plan.json
```

The `plan` command reads a manifest and records resumable jobs in the SQLite
ledger. It does not download data yet.

`manifest-from-listing` expects a JSON array of share file records. It accepts
common fields such as `path`, `isdir`, `server_mtime`, `mtime`, `md5`, and
`fs_id`. Directory records are skipped; file records become manifest entries.

## Run planned jobs

For local testing, `run-planned` can copy payloads from a local directory that
mirrors the remote transfer path:

```powershell
python -m baidu_pan_sync.cli run-planned `
  --config config.example.yaml `
  --payload-root D:/workspace/test-payloads `
  --output work/run.json
```

Production should replace the local payload downloader with the BaiduPCS-Go
adapter in `baidu_pan_sync/baidupcs.py`.

## Production daily sync

After logging in with a real account, save the current browser cookie string to a
local file such as `D:/workspace/baidu-pan-sync/secrets/baidu.cookies.txt`.
For password-protected share links, Baidu also uses a share-specific `sekey`.
It may appear as a `BDCLND` cookie after you click the extraction button in the
browser, or only as the `sekey` query parameter on the page's `/share/list`
network request. Store those values in an ignored JSON file such as
`D:/workspace/baidu-pan-sync/secrets/baidu-share-sekeys.json`, keyed by the share
feature id:

```json
{
  "1p5mVdIkCqg7ibniyyoJGQA": "BDCLND value for that share"
}
```

`config.example.yaml` contains one real sample subscription and disables the
placeholder `source_b` and `source_c` entries. Before using three subscriptions,
replace their placeholder URLs with real Baidu share URLs like
`https://pan.baidu.com/s/1...?...` and set `enabled: true`.

Run the complete daily flow:

```powershell
python -m baidu_pan_sync.cli sync-baidu-share `
  --config D:/workspace/baidu-pan-sync/config.example.yaml `
  --cookie-file D:/workspace/baidu-pan-sync/secrets/baidu.cookies.txt `
  --share-sekeys-file D:/workspace/baidu-pan-sync/secrets/baidu-share-sekeys.json `
  --baidupcs-bin D:/path/to/BaiduPCS-Go.exe `
  --baidupcs-config-dir D:/workspace/baidu-pan-sync/.pcs-config `
  --output D:/workspace/baidu-pan-sync/work/sync.json
```

For each configured subscription, this command:

1. reads the live share file list,
2. compares it with the SQLite ledger,
3. transfers only newly discovered `fs_id` values to the configured fixed remote
   directory such as `/auto-sync/source_a`,
4. downloads pending files with BaiduPCS-Go,
5. verifies local file size,
6. marks successful jobs `VERIFIED`.

It does not delete files from `/auto-sync/source_a`. It also does not call
BaiduPCS-Go's full-share `transfer` command during daily sync.

If Baidu's share web API returns `errno 9019` during discovery, the command stops
by default because selective transfer cannot be proven safe. To explicitly fall
back to BaiduPCS-Go's full-share transfer for that run, add:

```powershell
  --allow-full-transfer-fallback
```

This fallback may transfer the whole share into the configured remote staging
directory. Use it only when accepting that BaiduPCS-Go will handle duplicate
remote files and remote space behavior.

## Manual BaiduPCS-Go helpers

Manually transfer a configured share into your Baidu Netdisk remote staging
directory:

```powershell
python -m baidu_pan_sync.cli transfer-baidupcs `
  --config config.example.yaml `
  --subscription-id source_a `
  --baidupcs-bin D:/path/to/BaiduPCS-Go.exe `
  --baidupcs-config-dir D:/workspace/baidu-pan-sync/.pcs-config `
  --output work/transfer.json
```

Do not use `transfer-baidupcs` as the daily automation entrypoint. It is a
manual full-share transfer helper.

The older manifest-based helper is still useful for testing a prepared listing:

```powershell
python -m baidu_pan_sync.cli plan-and-transfer-baidupcs `
  --config config.example.yaml `
  --manifest work/source_a.manifest.json `
  --subscription-id source_a `
  --baidupcs-bin D:/path/to/BaiduPCS-Go.exe `
  --baidupcs-config-dir D:/workspace/baidu-pan-sync/.pcs-config `
  --output work/plan-transfer.json
```

This command skips remote transfer when the manifest contains only files already
known to the ledger, but it still uses BaiduPCS-Go's full-share transfer command
when new files exist. Use `sync-baidu-share` for selective per-file transfer.

After `plan` has recorded pending jobs, use BaiduPCS-Go to download the
transferred remote files:

```powershell
python -m baidu_pan_sync.cli run-baidupcs `
  --config config.example.yaml `
  --baidupcs-bin D:/path/to/BaiduPCS-Go.exe `
  --baidupcs-config-dir D:/workspace/baidu-pan-sync/.pcs-config `
  --output work/run.json
```

The BaiduPCS-Go adapter always sets `BAIDUPCS_GO_CONFIG_DIR` so this service does
not share current-directory or login state with an interactive BaiduPCS-Go
session.

Share transfer is implemented in `BaiduPcsGo.transfer_share(url, passcode,
remote_transfer_root)`. It runs `cd <remote_transfer_root>` followed by
`transfer <url> <passcode>`, matching BaiduPCS-Go's current behavior where
transfer saves into the active remote work directory.

## Daily scheduling

Use Windows Task Scheduler to run the `sync-baidu-share` command at 16:00
Asia/Shanghai every day.

Register the task:

```powershell
powershell -ExecutionPolicy Bypass -File D:/workspace/baidu-pan-sync/scripts/register-windows-task.ps1 `
  -CookieFile D:/workspace/baidu-pan-sync/secrets/baidu.cookies.txt `
  -BaiduPcsBin D:/path/to/BaiduPCS-Go.exe
```

Run once manually before enabling unattended use:

```powershell
powershell -ExecutionPolicy Bypass -File D:/workspace/baidu-pan-sync/scripts/run-daily-sync.ps1 `
  -CookieFile D:/workspace/baidu-pan-sync/secrets/baidu.cookies.txt `
  -BaiduPcsBin D:/path/to/BaiduPCS-Go.exe
```
