#!/usr/bin/env bash
# Remove o proxy d3d9.dll (mod menu) da pasta do PES 2016.
#
# Uso:
#   ./uninstall.sh
#   GAME_DIR="/caminho/para/Pro Evolution Soccer 2016" ./uninstall.sh
#
# Nao mexe em saves. Depois de remover, o jogo volta a carregar o DXVK
# direto do sistema.
set -euo pipefail

GAME_DIR="${GAME_DIR:-$HOME/.var/app/com.usebottles.bottles/data/bottles/bottles/Games/drive_c/Games/Pro Evolution Soccer 2016}"

if [ ! -d "$GAME_DIR" ]; then
    echo "Pasta do jogo nao encontrada: $GAME_DIR" >&2
    exit 1
fi

removidos=0
for f in d3d9.dll d3d9_real.dll modmenu.log; do
    if [ -f "$GAME_DIR/$f" ]; then
        rm -f "$GAME_DIR/$f"
        echo "removido: $f"
        removidos=$((removidos + 1))
    fi
done

if [ "$removidos" -eq 0 ]; then
    echo "Nada para remover em: $GAME_DIR"
else
    echo
    echo "Pronto. O override d3d9=n,b pode ficar (nao atrapalha)."
fi
