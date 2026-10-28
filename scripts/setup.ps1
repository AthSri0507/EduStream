# EduStream one-time setup (Windows PowerShell 5.1+).
# Run from anywhere:
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 [-SkipModels]
#
# 1. creates .venv in the repo root (Python 3.10)
# 2. installs the pinned packages from requirements.lock
# 3. copies .env.example to .env if .env does not exist yet
# 4. downloads the Whisper models into models\ (skip with -SkipModels)
# 5. runs scripts\preflight.ps1

param(
    [switch]$SkipModels,
    [string]$Python = "py"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"

# --------------------------------------------------
# 1. Virtual environment
# --------------------------------------------------

if (-not (Test-Path $VenvPy)) {
    Write-Host "Creating .venv with Python 3.10 ..."
    if ($Python -eq "py") {
        & py -3.10 -m venv "$Venv"
    } else {
        & "$Python" -m venv "$Venv"
    }
    if ($LASTEXITCODE -ne 0) { throw "Could not create .venv (is Python 3.10 installed?)" }
}

# --------------------------------------------------
# 2. Pinned packages
# --------------------------------------------------

Write-Host "Installing pinned packages from requirements.lock ..."
& "$VenvPy" -m pip install --disable-pip-version-check --quiet -r (Join-Path $Root "requirements.lock")
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# --------------------------------------------------
# 3. Local configuration
# --------------------------------------------------

$EnvFile = Join-Path $Root ".env"
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $Root ".env.example") $EnvFile
    Write-Host "Created .env from .env.example - add your free API keys there (needed from M2)."
}

# --------------------------------------------------
# 4. Whisper models (offline use later: local_files_only=True)
# --------------------------------------------------

if (-not $SkipModels) {
    foreach ($Model in @("base.en", "small.en")) {
        $Target = Join-Path $Root "models\$Model"
        if (Test-Path (Join-Path $Target "model.bin")) {
            Write-Host "Model $Model already present."
            continue
        }
        Write-Host "Downloading Whisper model $Model ..."
        & "$VenvPy" -c "import sys; from faster_whisper import download_model; download_model(sys.argv[1], output_dir=sys.argv[2])" $Model "$Target"
        if ($LASTEXITCODE -ne 0) { throw "Model download failed: $Model" }
    }
}

# --------------------------------------------------
# 4b. Embedding model for the assistant's hybrid search (loaded offline later; ARCHITECTURE §8.5)
# --------------------------------------------------

if (-not $SkipModels) {
    Write-Host "Downloading the embedding model (bge-small-en-v1.5, about 70 MB) ..."
    & "$VenvPy" -c "import sys; from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir=sys.argv[1])" (Join-Path $Root "models\fastembed")
    if ($LASTEXITCODE -ne 0) { throw "Embedding model download failed" }
}

# --------------------------------------------------
# 5. Preflight
# --------------------------------------------------

& powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "preflight.ps1")
exit $LASTEXITCODE
