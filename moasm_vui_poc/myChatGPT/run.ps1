$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectDir ".venv"
$Python = Join-Path $VenvDir "Scripts\python.exe"
$env:PYTHONDONTWRITEBYTECODE = "1"

if (-not (Test-Path $Python)) {
  py -3 -m venv --without-pip --system-site-packages $VenvDir
}

$Cfg = Join-Path $VenvDir "pyvenv.cfg"
if (Test-Path $Cfg) {
  $Text = Get-Content -LiteralPath $Cfg -Raw
  $Text = $Text -replace "include-system-site-packages = false", "include-system-site-packages = true"
  Set-Content -LiteralPath $Cfg -Value $Text -Encoding UTF8
}

& $Python -c "import PIL, pygments, requests, fitz; print('dependency check ok')"
if ($LASTEXITCODE -ne 0) {
  & $Python -m pip install -r (Join-Path $ProjectDir "requirements.txt")
  if ($LASTEXITCODE -ne 0) {
    throw "Required Python packages are missing. Install them with: python -m pip install -r requirements.txt"
  }
}

& $Python (Join-Path $ProjectDir "main.py")
