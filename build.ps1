param(
    [string] $Python = "python"
)

$ErrorActionPreference = "Stop"
$repoRoot = $PSScriptRoot
$distDir = Join-Path $repoRoot "dist"
$buildInfoPath = Join-Path $repoRoot "BUILD_INFO.json"

& $Python (Join-Path $repoRoot "scripts\write_build_info.py")
if ($LASTEXITCODE -ne 0) {
    throw "BUILD_INFO.json の生成に失敗しました。終了コード: $LASTEXITCODE"
}
$buildInfo = Get-Content -Raw -Encoding UTF8 $buildInfoPath | ConvertFrom-Json
if ($buildInfo.version -notmatch '^\d+\.\d+\.\d+(?:[.-][0-9A-Za-z.-]+)?$') {
    throw "pyproject.toml の version が不正です: $($buildInfo.version)"
}
if ($buildInfo.commit -ne "dev" -and $buildInfo.commit -notmatch '^[0-9a-f]{40}$') {
    throw "BUILD_INFO.json の commit が不正です: $($buildInfo.commit)"
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

$isccDirectory = Split-Path -Parent $iscc
$languageFile = Join-Path $isccDirectory "Languages\Japanese.isl"
if (-not (Test-Path -LiteralPath $languageFile)) {
    throw "Japanese.isl がありません。Inno Setup 6.5.0 以降をインストールしてください。"
}

New-Item -ItemType Directory -Force -Path $distDir | Out-Null
$scriptPath = Join-Path $repoRoot "installer\PotteryVolume.iss"
& $iscc "/DAppVersion=$($buildInfo.version)" "/DCommitSha=$($buildInfo.commit)" $scriptPath
if ($LASTEXITCODE -ne 0) {
    throw "ISCC.exe failed with exit code $LASTEXITCODE."
}

Write-Host "Built: $(Join-Path $distDir 'PotteryVolume-Setup.exe')"
