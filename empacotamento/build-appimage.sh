#!/usr/bin/env bash
#
# Gera a AppImage do PES 2016 ML-BL Editor (Linux x86_64).
#
#   Uso:  ./empacotamento/build-appimage.sh [arquivo-de-saida.AppImage]
#
# O que ele faz:
#   1. baixa um Python portátil (python-build-standalone) com Tcl/Tk;
#   2. monta o AppDir (Python + fontes + ícone + .desktop + AppRun);
#   3. baixa o appimagetool e empacota tudo num .AppImage único.
#
# O arquivo final não depende de nada instalado na máquina de quem for usar.
# Precisa apenas de: curl, tar, python3 (para descobrir as URLs) e ~500 MB
# livres em /tmp (ou em $TMPDIR).
#
# Variáveis opcionais: PY_SERIE (padrão 3.12), TMPDIR.

set -euo pipefail

AQUI="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
RAIZ="$(dirname "$AQUI")"
SAIDA="${1:-$RAIZ/PES2016-MLBL-Editor-PC-x86_64.AppImage}"
TRABALHO="${TMPDIR:-/tmp}/pes2016-appimage-build"
PY_SERIE="${PY_SERIE:-3.12}"
PY_API="https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
AIT_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"

echo "==> pasta de trabalho: $TRABALHO"
rm -rf "$TRABALHO"
mkdir -p "$TRABALHO"
cd "$TRABALHO"

echo "==> procurando o Python portátil mais recente ($PY_SERIE) para Linux"
URL="$(python3 - "$PY_SERIE" "$PY_API" <<'PY'
import json, sys, urllib.request
serie, api = sys.argv[1], sys.argv[2]
dados = json.load(urllib.request.urlopen(api))
alvo = "cpython-%s." % serie
sufixo = "-x86_64-unknown-linux-gnu-install_only"
achados = {}
for a in dados["assets"]:
    nome = a["name"]
    if not nome.startswith(alvo):
        continue
    if nome.endswith(sufixo + "_stripped.tar.gz"):
        achados["stripped"] = a["browser_download_url"]
    elif nome.endswith(sufixo + ".tar.gz"):
        achados["normal"] = a["browser_download_url"]
# preferimos a variante "stripped" (bem menor, com Tcl/Tk do mesmo jeito)
print(achados.get("stripped") or achados.get("normal") or "")
PY
)"
if [ -z "$URL" ]; then
    echo "erro: não encontrei o Python $PY_SERIE para Linux" >&2
    exit 1
fi
echo "    $URL"
curl -sSL --retry 3 -o python.tar.gz "$URL"
mkdir -p python
tar -xzf python.tar.gz -C python --strip-components=1
"$TRABALHO/python/bin/python3" \
    -c "import tkinter, zlib; print('    Python portátil OK - Tk', tkinter.TkVersion)"

echo "==> montando o AppDir"
APPDIR="$TRABALHO/PES2016-MLBL-Editor.AppDir"
mkdir -p "$APPDIR/usr/share/pes2016mlbl/pes2016mlbl" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps" \
         "$APPDIR/usr/python"

cp "$RAIZ/codigo-fonte-pc/main.py" "$APPDIR/usr/share/pes2016mlbl/"
cp "$RAIZ/codigo-fonte-pc/pes2016mlbl/"*.py "$APPDIR/usr/share/pes2016mlbl/pes2016mlbl/"
cp -r python/bin python/lib python/share "$APPDIR/usr/python/"

cp "$AQUI/icone.png" "$APPDIR/pes2016-mlbl-editor.png"
cp "$AQUI/icone.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/pes2016-mlbl-editor.png"
cp "$AQUI/pes2016-mlbl-editor.desktop" "$APPDIR/"
install -m 755 "$AQUI/AppRun" "$APPDIR/AppRun"
ln -sf pes2016-mlbl-editor.png "$APPDIR/.DirIcon"

echo "==> baixando o appimagetool"
curl -sSL --retry 3 -o appimagetool "$AIT_URL"
chmod +x appimagetool
./appimagetool --appimage-extract >/dev/null

echo "==> empacotando (squashfs + AppImage)"
ARCH=x86_64 ./squashfs-root/AppRun --no-appstream "$APPDIR" "$SAIDA"
chmod +x "$SAIDA"

echo "==> pronto: $SAIDA"
ls -la "$SAIDA"
sha256sum "$SAIDA"
