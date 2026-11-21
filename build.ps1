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
    $languageDirectories = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6"),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6"),
        (Join-Path $env:ProgramFiles "Inno Setup 6"),
        $isccDirectory
    ) | Where-Object { $_ } | Select-Object -Unique

    $languageFile = $null
    foreach ($directory in $languageDirectories) {
        $candidate = Join-Path $directory "Languages\Japanese.isl"
        if (Test-Path -LiteralPath $candidate) {
            $languageFile = $candidate
            break
        }
    }

    if (-not $languageFile) {
        $officialLanguageUrl = "https://raw.githubusercontent.com/jrsoftware/issrc/main/Files/Languages/Japanese.isl"
        foreach ($directory in $languageDirectories) {
            if (-not (Test-Path -LiteralPath (Join-Path $directory "ISCC.exe"))) {
                continue
            }
            $languageDirectory = Join-Path $directory "Languages"
            $candidate = Join-Path $languageDirectory "Japanese.isl"
            try {
                New-Item -ItemType Directory -Force -Path $languageDirectory | Out-Null
                Invoke-WebRequest -UseBasicParsing -Uri $officialLanguageUrl -OutFile $candidate
                if (Test-Path -LiteralPath $candidate) {
                    $languageFile = $candidate
                    break
                }
            } catch {
                Write-Warning "Japanese.isl を $candidate に保存できませんでした: $_"
            }
        }
    }

    if (-not $languageFile) {
        throw "Japanese.isl を取得できません。Inno Setup 6.5.0 以降をインストールしてください。"
    }
}

New-Item -ItemType Directory -Force -Path $distDir | Out-Null
$scriptPath = Join-Path $repoRoot "installer\PotteryVolume.iss"
& $iscc "/DAppVersion=$($buildInfo.version)" "/DCommitSha=$($buildInfo.commit)" $scriptPath
if ($LASTEXITCODE -ne 0) {
    throw "ISCC.exe failed with exit code $LASTEXITCODE."
}

Write-Host "Built: $(Join-Path $distDir 'PotteryVolume-Setup.exe')"
