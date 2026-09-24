# Start the AIBP Meeting Agent validation API on port 8000.
#
#   .\scripts\start_api.ps1                         # http://127.0.0.1:8000 (enough for a Dev Tunnel)
#   .\scripts\start_api.ps1 -BindAddress 0.0.0.0    # also reachable from other machines on the LAN
#
# The API needs no credentials and reads no .env. Stop it with Ctrl+C.

param(
    [int]$Port = 8000,
    [string]$BindAddress = "127.0.0.1"
)

$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "No virtual environment at $repo\.venv. Create it first:"
    Write-Host "  python -m venv .venv"
    Write-Host "  .venv\Scripts\python -m pip install -r requirements.txt"
    exit 1
}

Write-Host "Starting AIBP Meeting Agent API on http://${BindAddress}:$Port  (docs: http://127.0.0.1:$Port/docs)"
& $python -m uvicorn meeting_agent.api:app --host $BindAddress --port $Port
