param(
    [string] $Python = "python"
)

$ErrorActionPreference = "Stop"
$repoRoot = $PSScriptRoot
$distDir = Join-Path $repoRoot "dist"
$source = Join-Path $repoRoot "pottery_volume_bootstrap.pyw"

$tempDir = $env:RUNNER_TEMP
if (-not $tempDir) {
    $tempDir = [System.IO.Path]::GetTempPath()
}
$buildTempDir = Join-Path $tempDir ("PotteryVolume-Installer-" + [guid]::NewGuid().ToString("N"))
$versionFile = Join-Path $buildTempDir "BOOTSTRAP_VERSION"
$specTempDir = Join-Path $buildTempDir "spec"
$workTempDir = Join-Path $buildTempDir "work"
New-Item -ItemType Directory -Force -Path $buildTempDir, $specTempDir, $workTempDir | Out-Null

$version = $env:GITHUB_SHA
if (-not $version -and (Get-Command git -ErrorAction SilentlyContinue)) {
    $version = (& git -C $repoRoot rev-parse HEAD 2>$null).Trim()
}
if ($version -notmatch '^[0-9a-fA-F]{40}$') {
    $version = "dev"
}
[System.IO.File]::WriteAllText($versionFile, $version, [System.Text.Encoding]::ASCII)

New-Item -ItemType Directory -Force -Path $distDir | Out-Null
Push-Location $repoRoot
try {
    & $Python -m PyInstaller --noconfirm --clean --onefile --noconsole `
        --name PotteryVolume `
        --distpath $distDir `
        --workpath $workTempDir `
        --specpath $specTempDir `
        --add-data "$versionFile;." `
        $source
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
    Remove-Item -LiteralPath $versionFile -Force -ErrorAction SilentlyContinue
}

$isccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
$iscc = if ($isccCommand) { $isccCommand.Source } else { $null }
if (-not $iscc) {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    )
    $iscc = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $iscc) {
    throw "ISCC.exe が見つかりません。Inno Setup 6.5.0 以降をインストールしてください。"
}

$languageFile = Join-Path (Split-Path -Parent $iscc) "Languages\Japanese.isl"
if (-not (Test-Path -LiteralPath $languageFile)) {
    throw "Japanese.isl がありません。Inno Setup 6.5.0 以降をインストールしてください。"
}

& $iscc (Join-Path $repoRoot "installer\PotteryVolume.iss")
if ($LASTEXITCODE -ne 0) {
    throw "ISCC.exe failed with exit code $LASTEXITCODE."
}

Write-Host "Built: $(Join-Path $distDir 'PotteryVolume-Setup.exe')"
