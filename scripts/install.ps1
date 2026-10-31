# Manual install of token-routing into one project (no plugin system).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\install.ps1 C:\path\to\your\project
# It copies skills, agents and scripts into <project>\.claude\.
# It never touches your routing table, lessons or history (they are created on first use).
param([Parameter(Mandatory = $true)][string]$Project)
$ErrorActionPreference = "Stop"

$Src = Join-Path (Split-Path -Parent $PSScriptRoot) "plugins\token-routing"
if (-not (Test-Path $Project -PathType Container)) { throw "Project folder not found: $Project" }
$Dest = Join-Path (Resolve-Path $Project) ".claude"

foreach ($d in "skills", "agents", "routing") { New-Item -ItemType Directory -Force -Path (Join-Path $Dest $d) | Out-Null }

Get-ChildItem (Join-Path $Src "skills") -Directory | ForEach-Object {
  $target = Join-Path $Dest "skills\$($_.Name)"
  if (Test-Path $target) { Remove-Item $target -Recurse -Force }
  Copy-Item $_.FullName $target -Recurse
}
Copy-Item (Join-Path $Src "agents\*.md") (Join-Path $Dest "agents") -Force
Copy-Item (Join-Path $Src "routing\*.py") (Join-Path $Dest "routing") -Force
foreach ($d in "defaults", "templates") {
  $target = Join-Path $Dest "routing\$d"
  if (Test-Path $target) { Remove-Item $target -Recurse -Force }
  Copy-Item (Join-Path $Src "routing\$d") $target -Recurse
}

Write-Host "Installed into $Dest"
Write-Host "Next: paste $Src\CLAUDE.routing.md into your project's CLAUDE.md, restart Claude Code, run /orchestrate <request>."
