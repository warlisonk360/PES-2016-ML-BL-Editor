# Gera o .exe do PES 2016 ML-BL Editor (Windows x64).
#
#   Uso (PowerShell, na pasta do repositório):
#       .\empacotamento\build-exe-windows.ps1
#
# Requer o Python 3.10+ no PATH.  O .exe final sai com o interpretador Python,
# o Tcl/Tk e os módulos embutidos: não é preciso instalar mais nada para rodar
# (nem Python, nem runtime nenhum).

$ErrorActionPreference = "Stop"

$Aqui    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Raiz    = Split-Path -Parent $Aqui
$Fonte   = Join-Path $Raiz "codigo-fonte-pc"
$Destino = Join-Path $Raiz "PES2016-MLBL-Editor-Windows-x64.exe"

Write-Host "==> instalando PyInstaller + Pillow"
python -m pip install --upgrade pip
python -m pip install --quiet pyinstaller pillow

Write-Host "==> rodando os testes do nucleo"
python (Join-Path $Fonte "test_core.py")
if ($LASTEXITCODE -ne 0) { throw "os testes falharam" }

Write-Host "==> gerando o .exe"
Push-Location $Fonte
try {
    python -m PyInstaller --noconfirm --clean --onefile --windowed `
        --name "PES2016-MLBL-Editor" `
        --icon (Join-Path $Aqui "icone.ico") `
        --version-file (Join-Path $Aqui "version.txt") `
        main.py
    if ($LASTEXITCODE -ne 0) { throw "o PyInstaller falhou" }
}
finally {
    Pop-Location
}

Copy-Item (Join-Path $Fonte "dist\PES2016-MLBL-Editor.exe") $Destino -Force
$tamanho = [math]::Round((Get-Item $Destino).Length / 1MB, 1)
Write-Host "==> pronto: $Destino ($tamanho MB)"
