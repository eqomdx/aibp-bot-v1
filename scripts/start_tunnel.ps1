# Expose the local API (port 8000) over public HTTPS with Microsoft Dev Tunnels.
#
#   .\scripts\start_tunnel.ps1
#
# Uses a persistent, named tunnel so the public URL stays the same between runs
# and Copilot Studio doesn't need reconfiguring. The first run creates it with
# anonymous access (demo only - anyone with the URL can call the API).
# Run .\scripts\start_api.ps1 in another terminal first. Stop with Ctrl+C.
#
# One-off alternative with a new random URL each time:
#   devtunnel host -p 8000 --allow-anonymous

param(
    [string]$TunnelId = "aibp-meeting-agent",
    [int]$Port = 8000
)

# Exit codes are checked explicitly: in Windows PowerShell 5.1, "Stop" would turn
# devtunnel's expected stderr (e.g. "Tunnel not found") into a fatal error.
$devtunnel = (Get-Command devtunnel -ErrorAction SilentlyContinue).Source
if (-not $devtunnel) {
    $candidate = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\devtunnel.exe"
    if (Test-Path $candidate) { $devtunnel = $candidate }
}
if (-not $devtunnel) {
    Write-Host "devtunnel is not installed. Run: winget install Microsoft.devtunnel"
    exit 1
}

$user = cmd /c "`"$devtunnel`" user show 2>&1" | Out-String
if ($user -match "Not logged in") {
    Write-Host "Not logged in to Dev Tunnels. Run: devtunnel user login   (then re-run this script)"
    exit 1
}

cmd /c "`"$devtunnel`" show $TunnelId >nul 2>&1"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Creating tunnel '$TunnelId' with anonymous access on port $Port ..."
    & $devtunnel create $TunnelId --allow-anonymous --description "AIBP Meeting Agent API (demo)"
    if ($LASTEXITCODE -ne 0) { Write-Host "Could not create tunnel '$TunnelId'. Try another name: -TunnelId <name>"; exit 1 }
    & $devtunnel port create $TunnelId --port-number $Port
    if ($LASTEXITCODE -ne 0) { Write-Host "Could not add port $Port to tunnel '$TunnelId'."; exit 1 }
}

Write-Host "Hosting tunnel '$TunnelId'. Copy the 'Connect via browser' URL for port $Port into Copilot Studio."
& $devtunnel host $TunnelId
