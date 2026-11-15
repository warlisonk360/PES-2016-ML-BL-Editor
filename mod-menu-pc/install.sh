#!/usr/bin/env bash
# Instala o proxy d3d9.dll (mod menu) na pasta do PES 2016.
#
# Uso:
#   ./install.sh                      # tenta achar a garrafa "Games" do Bottles
#   GAME_DIR="/caminho/para/Pro Evolution Soccer 2016" ./install.sh
#
# O que faz:
#   1. copia build/d3d9.dll  -> <jogo>/d3d9.dll        (proxy)
#   2. copia a d3d9 do syswow64 -> <jogo>/d3d9_real.dll (DXVK renomeado)
#   3. confere se a garrafa tem o override d3d9=n,b
#
# Para desfazer: ./uninstall.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PROXY="$HERE/build/d3d9.dll"

GAME_DIR="${GAME_DIR:-$HOME/.var/app/com.usebottles.bottles/data/bottles/bottles/Games/drive_c/Games/Pro Evolution Soccer 2016}"
SYSWOW64="${SYSWOW64:-$HOME/.var/app/com.usebottles.bottles/data/bottles/bottles/Games/drive_c/windows/syswow64}"
BOTTLE_YML="${BOTTLE_YML:-$HOME/.var/app/com.usebottles.bottles/data/bottles/bottles/Games/bottle.yml}"

if [ ! -f "$PROXY" ]; then
    echo "Proxy nao encontrado: $PROXY" >&2
    echo "Rode ./build.sh primeiro." >&2
    exit 1
fi
if [ ! -d "$GAME_DIR" ]; then
    echo "Pasta do jogo nao encontrada: $GAME_DIR" >&2
    echo "Defina GAME_DIR=/caminho/da/pasta." >&2
    exit 1
fi
if [ ! -f "$SYSWOW64/d3d9.dll" ]; then
    echo "d3d9.dll do DXVK nao encontrada em: $SYSWOW64" >&2
    exit 1
fi

if [ -f "$GAME_DIR/d3d9.dll" ] || [ -f "$GAME_DIR/d3d9_real.dll" ]; then
    echo "Ja existe d3d9.dll/d3d9_real.dll na pasta do jogo."
    echo "Rode ./uninstall.sh antes (ou confirme que e uma instalacao sua)." >&2
    exit 1
fi

cp "$PROXY" "$GAME_DIR/d3d9.dll"
cp "$SYSWOW64/d3d9.dll" "$GAME_DIR/d3d9_real.dll"
rm -f "$GAME_DIR/modmenu.log"

echo "Instalado em: $GAME_DIR"
echo "  d3d9.dll      (proxy, $(stat -c%s "$GAME_DIR/d3d9.dll") bytes)"
echo "  d3d9_real.dll (DXVK, $(stat -c%s "$GAME_DIR/d3d9_real.dll") bytes)"

if [ -f "$BOTTLE_YML" ] && ! grep -qE "^  d3d9:" "$BOTTLE_YML"; then
    echo
    echo "ATENCAO: falta o override d3d9 na garrafa."
    echo "No Bottles: Garrafa -> Configuracoes -> DLL Overrides"
    echo "adicione  d3d9 = n,b  (ou edite $BOTTLE_YML)."
fi
