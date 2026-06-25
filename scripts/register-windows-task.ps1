param(
    [string]$TaskName = "BaiduPanIncrementalSync",
    [string]$ProjectRoot = "D:\workspace\baidu-pan-sync",
    [Parameter(Mandatory = $true)]
    [string]$CookieFile,
    [Parameter(Mandatory = $true)]
    [string]$BaiduPcsBin
)

$ErrorActionPreference = "Stop"

$runner = Join-Path $ProjectRoot "scripts\run-daily-sync.ps1"
$arguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$runner`"",
    "-ProjectRoot", "`"$ProjectRoot`"",
    "-CookieFile", "`"$CookieFile`"",
    "-BaiduPcsBin", "`"$BaiduPcsBin`""
) -join " "

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Daily -At "16:00"

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Description "Incrementally sync Baidu Netdisk share subscriptions at 16:00 every day." `
    -Force
