param(
    [string]$Python = "",
    [string]$Name = "ArrumaDir"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if ([string]::IsNullOrWhiteSpace($Python)) {
    $BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (Test-Path $BundledPython) {
        $Python = $BundledPython
    } elseif ($PythonCommand -and $PythonCommand.Source -notlike "*\WindowsApps\python.exe") {
        $Python = $PythonCommand.Source
    } else {
        throw "Python nao encontrado. Instale Python 3.10+ ou passe -Python C:\caminho\python.exe"
    }
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Comando falhou ($LASTEXITCODE): $FilePath $Arguments"
    }
}

Invoke-Native -FilePath $Python -Arguments @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Native -FilePath $Python -Arguments @("-m", "pip", "install", "-e", ".[build]")
Invoke-Native -FilePath $Python -Arguments @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", $Name,
    "--paths", "src",
    "--hidden-import", "arruma_dir.hardware",
    "--hidden-import", "arruma_dir.project_cli",
    "--hidden-import", "arruma_dir.project_organizer",
    "src\arruma_dir\app.py"
)

Write-Host "EXE gerado em: $Root\dist\$Name\$Name.exe"
