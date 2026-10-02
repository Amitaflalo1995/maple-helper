# Installs (or upgrades to) the latest Inno Setup 6. packaging/installer.iss uses recent directives
# (WizardBackImageFile, *DynamicDark) that an older copy preinstalled on a runner image would reject.
$ErrorActionPreference = "Stop"
choco upgrade innosetup --yes --no-progress
if ($LASTEXITCODE -ne 0) { throw "choco upgrade innosetup failed" }
# any major version's folder ("Inno Setup 6", "Inno Setup 7"): choco installs the latest
$iscc = @("${env:ProgramFiles(x86)}", "$env:ProgramFiles") | ForEach-Object { Get-ChildItem "$_\Inno Setup *\ISCC.exe" -ErrorAction SilentlyContinue } |
    Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
if (-not $iscc) { throw "ISCC.exe not found after installing Inno Setup" }
Write-Host "Inno Setup: $((Get-Item $iscc).VersionInfo.ProductVersion) at $iscc"
