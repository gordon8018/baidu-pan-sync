param(
    [string]$ProjectRoot = "D:\workspace\baidu-pan-sync",
    [string]$ConfigPath = "D:\workspace\baidu-pan-sync\config.example.yaml",
    [Parameter(Mandatory = $true)]
    [string]$CookieFile,
    [string]$ShareSekeysFile = "D:\workspace\baidu-pan-sync\secrets\baidu-share-sekeys.json",
    [Parameter(Mandatory = $true)]
    [string]$BaiduPcsBin,
    [string]$BaiduPcsConfigDir = "D:\workspace\baidu-pan-sync\.pcs-config",
    [string]$OutputPath = "D:\workspace\baidu-pan-sync\work\sync.json"
)

$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputPath) | Out-Null
Set-Location $ProjectRoot

python -m baidu_pan_sync.cli sync-baidu-share `
    --config $ConfigPath `
    --cookie-file $CookieFile `
    --share-sekeys-file $ShareSekeysFile `
    --baidupcs-bin $BaiduPcsBin `
    --baidupcs-config-dir $BaiduPcsConfigDir `
    --output $OutputPath
