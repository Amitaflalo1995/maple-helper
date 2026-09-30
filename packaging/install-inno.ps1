# Installs (or upgrades to) the latest Inno Setup 6. packaging/installer.iss uses recent directives
# (WizardBackImageFile, *DynamicDark) that an older copy preinstalled on a runner image would reject.
$ErrorActionPreference = "Stop"
choco upgrade innosetup --yes --no-progress
if ($LASTEXITCODE -ne 0) { throw "choco upgrade innosetup failed" }
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "ISCC.exe not found after installing Inno Setup" }
Write-Host "Inno Setup: $((Get-Item $iscc).VersionInfo.ProductVersion) at $iscc"
