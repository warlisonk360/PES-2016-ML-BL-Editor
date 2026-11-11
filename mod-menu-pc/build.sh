#!/usr/bin/env bash
# Compila a DLL proxy d3d9.dll (32-bit Windows) usando Zig (sem sudo).
#
# Requisitos:
#   - Zig 0.13+ em $ZIG (padrao: /tmp/opencode/toolchain/zig/zig)
#   - ImGui em $IMGUI (padrao: /tmp/opencode/vendor/imgui)
#
# Uso:
#   ./build.sh
#   ZIG=/caminho/zig IMGUI=/caminho/imgui ./build.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ZIG="${ZIG:-/tmp/opencode/toolchain/zig/zig}"
IMGUI="${IMGUI:-/tmp/opencode/vendor/imgui}"
OUT="${OUT:-$HERE/build}"

if [ ! -x "$ZIG" ]; then
    echo "Zig nao encontrado em $ZIG" >&2
    echo "Baixe em https://ziglang.org/download/ e ajuste ZIG=..." >&2
    exit 1
fi
if [ ! -f "$IMGUI/imgui.cpp" ]; then
    echo "ImGui nao encontrado em $IMGUI" >&2
    echo "git clone --depth 1 https://github.com/ocornut/imgui.git $IMGUI" >&2
    exit 1
fi

mkdir -p "$OUT"
echo "Compilando d3d9.dll (i686, ImGui)..."
"$ZIG" c++ -target x86-windows-gnu -shared -O2 -DNDEBUG \
    -DWIN32_LEAN_AND_MEAN \
    -fno-exceptions -fno-rtti \
    -I"$IMGUI" -I"$IMGUI/backends" \
    "$HERE/src/dllmain.cpp" \
    "$IMGUI/imgui.cpp" \
    "$IMGUI/imgui_draw.cpp" \
    "$IMGUI/imgui_tables.cpp" \
    "$IMGUI/imgui_widgets.cpp" \
    "$IMGUI/backends/imgui_impl_dx9.cpp" \
    "$IMGUI/backends/imgui_impl_win32.cpp" \
    -luser32 -lgdi32 -lole32 -luuid -ldwmapi -limm32 \
    -Wl,--export-all-symbols \
    -o "$OUT/d3d9.dll"

# O linker do Zig decora exports __stdcall com @N.  O jogo importa os nomes
# sem decoracao, entao reescrevemos a tabela de nomes do PE.
echo "Ajustando nomes dos exports..."
python3 "$HERE/tools/fix_exports.py" "$OUT/d3d9.dll"

echo "OK: $OUT/d3d9.dll"
ls -l "$OUT/d3d9.dll"
