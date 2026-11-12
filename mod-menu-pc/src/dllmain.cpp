// Proxy d3d9.dll para o PES 2016 (32-bit, Wine/Proton).
//
// O jogo importa d3d9.dll (fornecido pelo DXVK). Colocamos esta DLL na pasta
// do jogo: ela carrega o DXVK renomeado (d3d9_real.dll), repassa as funcoes
// usadas e intercepta Direct3DCreate9 -> CreateDevice -> EndScene para
// desenhar um menu ImGui por cima do jogo.
//
// Etapa 1: so prova a injecao/hook e mostra um menu simples (tecla Insert).
// Nenhum recurso de trapaça e acionado aqui ainda.
//
// Compilar com build.sh (zig cc -target i686-windows-gnu).

#include <windows.h>
#include <d3d9.h>

#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "imgui.h"
#include "imgui_impl_dx9.h"
#include "imgui_impl_win32.h"

// O header do backend deixa esta declaracao comentada de proposito.
extern IMGUI_IMPL_API LRESULT ImGui_ImplWin32_WndProcHandler(
    HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam);

#ifndef VK_INSERT
#define VK_INSERT 0x2D
#endif

// Indices na vtable (ordem fixa do Direct3D 9).
static const int VTBL_D3D9_CREATEDEVICE = 16;   // IDirect3D9
static const int VTBL_D3D9_CREATEDEVICEEX = 20; // IDirect3D9Ex
static const int VTBL_DEV_ENDSCENE = 42;        // IDirect3DDevice9

static HMODULE g_self = nullptr;
static char g_log_path[MAX_PATH] = {0};
static bool g_menu_open = false;
static bool g_imgui_ready = false;
static bool g_safe_mode = false;
static bool g_autoscan = false;
static bool g_autoscan_done = false;
static HWND g_hwnd = nullptr;
static IDirect3DDevice9* g_device = nullptr;

// ---------------------------------------------------------------------------
// Log
// ---------------------------------------------------------------------------
static void init_paths(HMODULE self) {
    g_self = self;
    char path[MAX_PATH] = {0};
    GetModuleFileNameA(self, path, MAX_PATH);
    char* slash = strrchr(path, '\\');
    if (!slash) slash = strrchr(path, '/');
    if (slash) *(slash + 1) = 0;
    snprintf(g_log_path, sizeof(g_log_path), "%smodmenu.log", path);
    char flag[MAX_PATH];
    snprintf(flag, sizeof(flag), "%smodmenu_nohook.txt", path);
    g_safe_mode = GetFileAttributesA(flag) != INVALID_FILE_ATTRIBUTES;
    snprintf(flag, sizeof(flag), "%smodmenu_autoscan.txt", path);
    g_autoscan = GetFileAttributesA(flag) != INVALID_FILE_ATTRIBUTES;
}

static void logmsg(const char* fmt, ...) {
    if (!g_log_path[0]) return;
    FILE* f = fopen(g_log_path, "a");
    if (!f) return;
    SYSTEMTIME t;
    GetLocalTime(&t);
    fprintf(f, "[%02d:%02d:%02d] ", t.wHour, t.wMinute, t.wSecond);
    va_list ap;
    va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fputc('\n', f);
    fclose(f);
}

// ---------------------------------------------------------------------------
// Memoria do proprio jogo (Etapa 2)
// ---------------------------------------------------------------------------
// Como a DLL roda dentro do PES2016.exe, lemos/escrevemos direto na memoria.
// Tudo aqui so age quando o usuario aperta um botao do menu.
static const uint32_t PLAYER_RECORD_SIZE = 0xE4;
static const uint32_t PLAYER_NAME_OFFSET = 0x40;
static const uint32_t PLAYER_NAME_LEN = 46;
static const uint32_t PLAYER_ID_OFFSET = 0x38;
static const uint32_t PLAYER_HEIGHT_OFFSET = 0x0C;
static const uint32_t PLAYER_WEIGHT_OFFSET = 0x0D;
static const uint32_t PLAYER_INJURY_OFFSET = 0x0E;
static const int MONEY_SCALE = 100;
static const int MAX_HITS = 64;

struct PlayerCopy {
    uintptr_t base;
    uint32_t id;
    uint8_t injury;
};

static char g_player_name[32] = "WARLISON";
static PlayerCopy g_player_copies[8] = {};
static uint8_t g_player_injury_orig[8] = {};
static int g_player_copy_count = 0;
static bool g_player_found = false;

static int g_money_atual = 0;
static int g_money_novo = 0;
// Campos digitaveis como texto: com navegacao por teclado, InputInt vira tres
// itens de foco (campo + botoes +/-).  Texto numerico e um item so.
static char g_money_atual_buf[24] = "";
static char g_money_novo_buf[24] = "";
static uintptr_t g_money_addr[8] = {};
static int32_t g_money_raw[8] = {};
static int32_t g_money_antes[8] = {};   // valor original, para reverter
static int g_money_count = 0;
static bool g_money_found = false;
static bool g_money_pending = false;   // validacao de estabilidade pendente
static DWORD g_money_check_at = 0;

// Regiao legivel? (a protecao pode vir com flags extras, por isso a mascara)
static bool prot_readable(DWORD prot) {
    if (prot & PAGE_GUARD) return false;
    switch (prot & 0xFF) {
        case PAGE_READONLY:
        case PAGE_READWRITE:
        case PAGE_WRITECOPY:
        case PAGE_EXECUTE_READ:
        case PAGE_EXECUTE_READWRITE:
        case PAGE_EXECUTE_WRITECOPY:
            return true;
        default:
            return false;
    }
}

static bool prot_writable(DWORD prot) {
    switch (prot & 0xFF) {
        case PAGE_READWRITE:
        case PAGE_WRITECOPY:
        case PAGE_EXECUTE_READWRITE:
        case PAGE_EXECUTE_WRITECOPY:
            return true;
        default:
            return false;
    }
}

static bool safe_read(uintptr_t addr, void* dst, size_t n) {
    if (!addr || !dst || !n) return false;
    MEMORY_BASIC_INFORMATION mbi;
    if (!VirtualQuery((LPCVOID)addr, &mbi, sizeof(mbi))) return false;
    if (mbi.State != MEM_COMMIT || !prot_readable(mbi.Protect)) return false;
    uintptr_t end = (uintptr_t)mbi.BaseAddress + mbi.RegionSize;
    if (addr + n > end) return false;
    memcpy(dst, (const void*)addr, n);
    return true;
}

static bool safe_write(uintptr_t addr, const void* src, size_t n) {
    if (!addr || !src || !n) return false;
    MEMORY_BASIC_INFORMATION mbi;
    if (!VirtualQuery((LPCVOID)addr, &mbi, sizeof(mbi))) return false;
    if (mbi.State != MEM_COMMIT || !prot_writable(mbi.Protect)) return false;
    memcpy((void*)addr, src, n);
    return true;
}

// Procura "needle" nas regioes legiveis do processo.  Pula o proprio modulo
// (para nao achar o buffer do campo de texto do menu).
static int scan_bytes(const void* needle, size_t nlen, bool somente_gravavel,
                      uintptr_t* out, int max_out) {
    int achados = 0;
    if (!needle || nlen < 2) return 0;
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    uintptr_t addr = (uintptr_t)si.lpMinimumApplicationAddress;
    uintptr_t limite = (uintptr_t)si.lpMaximumApplicationAddress;
    const size_t chunk = 1u << 20;
    unsigned char* buf = (unsigned char*)malloc(chunk);
    if (!buf) return 0;

    while (addr < limite && achados < max_out) {
        MEMORY_BASIC_INFORMATION mbi;
        if (!VirtualQuery((LPCVOID)addr, &mbi, sizeof(mbi))) break;
        uintptr_t base = (uintptr_t)mbi.BaseAddress;
        uintptr_t next = base + mbi.RegionSize;
        if (next <= addr) break;

        if (mbi.State == MEM_COMMIT && (HMODULE)mbi.AllocationBase != g_self &&
            mbi.Type != MEM_IMAGE &&   // nao procurar dentro de DLLs/EXEs
            prot_readable(mbi.Protect) &&
            (!somente_gravavel || prot_writable(mbi.Protect))) {
            for (uintptr_t pos = base; pos < next && achados < max_out;) {
                size_t bloco = (size_t)(next - pos);
                if (bloco > chunk) bloco = chunk;
                memcpy(buf, (const void*)pos, bloco);
                for (size_t i = 0; i + nlen <= bloco && achados < max_out;
                     ++i) {
                    if (buf[i] == ((const unsigned char*)needle)[0] &&
                        memcmp(buf + i, needle, nlen) == 0) {
                        out[achados++] = pos + i;
                        i += nlen - 1;   // nao conta o mesmo hit duas vezes
                    }
                }
                pos += bloco;   // pequena perda nas bordas: aceitavel aqui
            }
        }
        addr = next;
    }
    free(buf);
    return achados;
}

// Acha as copias do registro do jogador e escolhe o grupo com o ID mais comum
// (mesma heuristica do treinador externo).
static void player_search() {
    g_player_found = false;
    g_player_copy_count = 0;
    size_t nlen = strlen(g_player_name);
    if (nlen < 2) {
        logmsg("busca: nome muito curto");
        return;
    }
    DWORD t0 = GetTickCount();
    uintptr_t hits[MAX_HITS];
    int nhits = scan_bytes(g_player_name, nlen, false, hits, MAX_HITS);
    logmsg("busca de '%s': %d ocorrencias", g_player_name, nhits);

    PlayerCopy cand[MAX_HITS];
    int nc = 0;
    for (int i = 0; i < nhits; ++i) {
        uintptr_t base = hits[i] - PLAYER_NAME_OFFSET;
        if (base > hits[i]) continue;
        unsigned char rec[PLAYER_RECORD_SIZE];
        if (!safe_read(base, rec, sizeof(rec))) continue;
        if (memcmp(rec + PLAYER_NAME_OFFSET, g_player_name, nlen) != 0) continue;
        if (nlen < PLAYER_NAME_LEN && rec[PLAYER_NAME_OFFSET + nlen] != 0)
            continue;
        unsigned char altura = rec[PLAYER_HEIGHT_OFFSET];
        unsigned char peso = rec[PLAYER_WEIGHT_OFFSET];
        if (altura < 140 || altura > 230 || peso < 30 || peso > 150) continue;
        bool repetido = false;
        for (int j = 0; j < nc; ++j)
            if (cand[j].base == base) repetido = true;
        if (repetido || nc >= MAX_HITS) continue;
        cand[nc].base = base;
        memcpy(&cand[nc].id, rec + PLAYER_ID_OFFSET, 4);
        cand[nc].injury = rec[PLAYER_INJURY_OFFSET];
        ++nc;
    }
    logmsg("registros validos: %d (%.1f s)", nc,
           (GetTickCount() - t0) / 1000.0);

    if (nc == 0) return;

    // Escolhe o ID nao-zero mais comum.
    uint32_t melhor_id = 0;
    int melhor_qtd = 0;
    for (int i = 0; i < nc; ++i) {
        if (!cand[i].id) continue;
        int qtd = 0;
        for (int j = 0; j < nc; ++j)
            if (cand[j].id == cand[i].id) ++qtd;
        if (qtd > melhor_qtd) {
            melhor_qtd = qtd;
            melhor_id = cand[i].id;
        }
    }

    for (int i = 0; i < nc && g_player_copy_count < 8; ++i) {
        if (melhor_id && cand[i].id != melhor_id) continue;
        g_player_copies[g_player_copy_count] =
            {cand[i].base, cand[i].id, cand[i].injury};
        g_player_injury_orig[g_player_copy_count] = cand[i].injury;
        ++g_player_copy_count;
    }
    g_player_found = g_player_copy_count > 0;
    if (g_player_found)
        logmsg("jogador escolhido: ID=%08x copias=%d lesao=%d", melhor_id,
               g_player_copy_count, g_player_copies[0].injury);
}

static void player_write_injury(uint8_t valor) {
    for (int i = 0; i < g_player_copy_count; ++i) {
        uintptr_t addr = g_player_copies[i].base + PLAYER_INJURY_OFFSET;
        uint8_t antes = 0;
        if (!safe_read(addr, &antes, 1)) continue;
        if (!safe_write(addr, &valor, 1)) continue;
        logmsg("lesao copia %d: %u -> %u (0x%08x)", i, antes, valor,
               (unsigned)addr);
        g_player_copies[i].injury = valor;
    }
}

static void player_revert_injury() {
    for (int i = 0; i < g_player_copy_count; ++i) {
        uintptr_t addr = g_player_copies[i].base + PLAYER_INJURY_OFFSET;
        uint8_t valor = g_player_injury_orig[i];
        if (!safe_write(addr, &valor, 1)) continue;
        logmsg("lesao copia %d revertida para %u (0x%08x)", i, valor,
               (unsigned)addr);
        g_player_copies[i].injury = valor;
    }
}

static void money_search() {
    g_money_found = false;
    g_money_count = 0;
    g_money_atual = atoi(g_money_atual_buf);
    if (g_money_atual <= 0) {
        logmsg("dinheiro: informe o saldo atual");
        return;
    }
    int32_t alvo = g_money_atual / MONEY_SCALE;
    DWORD t0 = GetTickCount();
    uintptr_t hits[MAX_HITS];
    int nhits = scan_bytes(&alvo, 4, true, hits, MAX_HITS);
    for (int i = 0; i < nhits && g_money_count < 8; ++i) {
        // Dinheiro em int32 alinhado; endereco desalinhado e quase sempre
        // coincidencia de buffer.
        if (hits[i] & 3) continue;
        int32_t raw = 0;
        if (!safe_read(hits[i], &raw, 4) || raw != alvo) continue;
        g_money_addr[g_money_count] = hits[i];
        g_money_raw[g_money_count] = raw;
        g_money_antes[g_money_count] = raw;   // valor original do jogo
        ++g_money_count;
    }
    g_money_found = g_money_count > 0;
    logmsg("dinheiro: alvo=%d achados=%d (%.1f s)", alvo, g_money_count,
           (GetTickCount() - t0) / 1000.0);

    // Confere os candidatos alguns quadros depois: endereco que ja mudou de
    // valor e lixo de buffer, nao o saldo do jogo.
    g_money_check_at = GetTickCount() + 500;
    g_money_pending = g_money_found;
}

// Chamado a cada quadro: descarta candidatos instaveis (valor ja mudou).
static void money_validate() {
    if (!g_money_pending) return;
    if (GetTickCount() < g_money_check_at) return;
    g_money_pending = false;
    int manteve = 0;
    for (int i = 0; i < g_money_count; ++i) {
        int32_t agora = 0;
        if (!safe_read(g_money_addr[i], &agora, 4) ||
            agora != g_money_antes[i]) {
            logmsg("dinheiro 0x%08x: descartado (valor instavel)",
                   (unsigned)g_money_addr[i]);
            continue;
        }
        g_money_addr[manteve] = g_money_addr[i];
        g_money_raw[manteve] = g_money_raw[i];
        g_money_antes[manteve] = g_money_antes[i];
        ++manteve;
    }
    if (manteve != g_money_count)
        logmsg("dinheiro: %d candidato(s) estavel(is) de %d", manteve,
               g_money_count);
    g_money_count = manteve;
    g_money_found = g_money_count > 0;
}

// Valor que esta agora na memoria (para mostrar no menu).
static int32_t money_current() {
    int32_t v = 0;
    if (g_money_count > 0 && safe_read(g_money_addr[0], &v, 4)) return v;
    return -1;
}

static void money_apply() {
    g_money_novo = atoi(g_money_novo_buf);
    if (g_money_novo <= 0) {
        logmsg("dinheiro: informe o novo saldo");
        return;
    }
    int32_t novo = g_money_novo / MONEY_SCALE;
    for (int i = 0; i < g_money_count; ++i) {
        uintptr_t addr = g_money_addr[i];
        int32_t antes = 0;
        if (!safe_read(addr, &antes, 4)) {
            logmsg("dinheiro 0x%08x: nao consegui ler, pulando",
                   (unsigned)addr);
            continue;
        }
        // Se o valor mudou desde a busca (outra tela/carregamento), nao grava:
        // o endereco pode ter sido reaproveitado por outra coisa.
        if (antes != g_money_antes[i]) {
            logmsg("dinheiro 0x%08x: valor mudou (%d, esperado %d), nao gravei",
                   (unsigned)addr, antes, g_money_antes[i]);
            continue;
        }
        if (!safe_write(addr, &novo, 4)) continue;
        logmsg("dinheiro 0x%08x: %d -> %d", (unsigned)addr, antes, novo);
    }
}

static void money_revert() {
    for (int i = 0; i < g_money_count; ++i) {
        if (!safe_write(g_money_addr[i], &g_money_antes[i], 4)) continue;
        logmsg("dinheiro 0x%08x revertido para %d", (unsigned)g_money_addr[i],
               g_money_antes[i]);
    }
}

// ---------------------------------------------------------------------------
// Acesso ao d3d9 real (DXVK renomeado para d3d9_real.dll)
// ---------------------------------------------------------------------------
static HMODULE load_real() {
    static HMODULE h = nullptr;
    if (h) return h;
    char path[MAX_PATH] = {0};
    GetModuleFileNameA(g_self, path, MAX_PATH);
    char* slash = strrchr(path, '\\');
    if (slash) *(slash + 1) = 0;
    char real[MAX_PATH];
    snprintf(real, sizeof(real), "%sd3d9_real.dll", path);
    h = LoadLibraryA(real);
    logmsg("LoadLibrary(%s) = %p", real, (void*)h);
    return h;
}

static void* real_proc(const char* name) {
    HMODULE h = load_real();
    return h ? (void*)GetProcAddress(h, name) : nullptr;
}

// ---------------------------------------------------------------------------
// Hook de vtable
// ---------------------------------------------------------------------------
// Troca um slot da vtable NO LUGAR (com VirtualProtect).
//
// Nao podemos substituir o ponteiro da vtable do objeto: o DXVK devolve
// objetos cujo layout interno depende da vtable original (trocar o ponteiro
// fazia o jogo pular para memoria invalida).  Patchar o slot preserva a
// identidade da vtable e funciona com qualquer tamanho de vtable.
static bool patch_vtable_slot(void** vtbl, int index, void* hook, void** orig) {
    if (!vtbl || index < 0) return false;
    if (vtbl[index] == hook) return true;   // ja patchado
    DWORD old = 0;
    if (!VirtualProtect(&vtbl[index], sizeof(void*), PAGE_READWRITE, &old)) {
        logmsg("VirtualProtect falhou (slot %d, err=%lu)", index,
               (unsigned long)GetLastError());
        return false;
    }
    if (orig) *orig = vtbl[index];
    vtbl[index] = hook;
    DWORD tmp = 0;
    VirtualProtect(&vtbl[index], sizeof(void*), old, &tmp);
    return true;
}

typedef HRESULT(STDMETHODCALLTYPE* PFN_CreateDevice)(
    IDirect3D9*, UINT, D3DDEVTYPE, HWND, DWORD,
    D3DPRESENT_PARAMETERS*, IDirect3DDevice9**);
typedef HRESULT(STDMETHODCALLTYPE* PFN_CreateDeviceEx)(
    IDirect3D9Ex*, UINT, D3DDEVTYPE, HWND, DWORD,
    D3DPRESENT_PARAMETERS*, D3DDISPLAYMODEEX*, IDirect3DDevice9Ex**);
typedef HRESULT(STDMETHODCALLTYPE* PFN_EndScene)(IDirect3DDevice9*);

static PFN_CreateDevice g_orig_CreateDevice = nullptr;
static PFN_CreateDeviceEx g_orig_CreateDeviceEx = nullptr;
static PFN_EndScene g_orig_EndScene = nullptr;

static HRESULT STDMETHODCALLTYPE hook_EndScene(IDirect3DDevice9* dev);
static HRESULT STDMETHODCALLTYPE hook_CreateDevice(
    IDirect3D9*, UINT, D3DDEVTYPE, HWND, DWORD,
    D3DPRESENT_PARAMETERS*, IDirect3DDevice9**);
static HRESULT STDMETHODCALLTYPE hook_CreateDeviceEx(
    IDirect3D9Ex*, UINT, D3DDEVTYPE, HWND, DWORD,
    D3DPRESENT_PARAMETERS*, D3DDISPLAYMODEEX*, IDirect3DDevice9Ex**);

// Subclasse da janela: sem isto o ImGui nao recebe mouse/teclado.
static WNDPROC g_orig_wndproc = nullptr;

static LRESULT CALLBACK hook_wndproc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    if (!g_menu_open)
        return CallWindowProcW(g_orig_wndproc, hwnd, msg, wp, lp);

    // Esc fecha o menu (e nao chega ao jogo).
    if (msg == WM_KEYDOWN && wp == VK_ESCAPE) {
        g_menu_open = false;
        logmsg("menu fechado (Esc)");
        return 1;
    }

    // Menu aberto = modal: o teclado vai so para o ImGui, nunca para o jogo.
    switch (msg) {
        case WM_KEYDOWN:
        case WM_KEYUP:
        case WM_CHAR:
        case WM_SYSKEYDOWN:
        case WM_SYSKEYUP:
        case WM_SYSCHAR:
            ImGui_ImplWin32_WndProcHandler(hwnd, msg, wp, lp);
            return 1;
        default:
            break;
    }
    if (ImGui_ImplWin32_WndProcHandler(hwnd, msg, wp, lp))
        return 1;
    return CallWindowProcW(g_orig_wndproc, hwnd, msg, wp, lp);
}

static void init_imgui(IDirect3DDevice9* dev, HWND hwnd) {
    if (g_imgui_ready || !dev || !hwnd) return;
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.IniFilename = nullptr;   // nao grava imgui.ini no jogo
    io.LogFilename = nullptr;
    // O jogo prende o cursor no X11, entao mouse absoluto nao funciona.
    // O menu e totalmente navegavel por teclado (setas, Enter, Esc).
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    ImGui::StyleColorsDark();
    ImGui_ImplWin32_Init(hwnd);
    if (!ImGui_ImplDX9_Init(dev)) {
        logmsg("ImGui_ImplDX9_Init FALHOU");
        return;
    }
    if (!g_orig_wndproc) {
        g_orig_wndproc = (WNDPROC)SetWindowLongPtrW(
            hwnd, GWLP_WNDPROC, (LONG_PTR)hook_wndproc);
        logmsg("WndProc subclassado (antigo=%p novo=%p)",
               (void*)g_orig_wndproc, (void*)hook_wndproc);
    }
    g_imgui_ready = true;
    logmsg("ImGui inicializado (hwnd=%p dev=%p)", (void*)hwnd, (void*)dev);
}

static HRESULT STDMETHODCALLTYPE hook_EndScene(IDirect3DDevice9* dev) {
    static bool antes = false;
    bool agora = (GetAsyncKeyState(VK_INSERT) & 0x8000) != 0;
    if (agora && !antes) {
        g_menu_open = !g_menu_open;
        logmsg("menu %s (Insert)", g_menu_open ? "ABERTO" : "fechado");
        if (g_menu_open && g_autoscan && !g_autoscan_done) {
            g_autoscan_done = true;
            logmsg("autoscan: procurando '%s'", g_player_name);
            player_search();
        }
    }
    antes = agora;

    if (g_menu_open && g_imgui_ready) {
        ImGui::GetIO().MouseDrawCursor = true;
        ImGui_ImplDX9_NewFrame();
        ImGui_ImplWin32_NewFrame();
        ImGui::NewFrame();
        money_validate();

        ImGui::SetNextWindowPos(ImVec2(40, 40), ImGuiCond_FirstUseEver);
        ImGui::SetNextWindowSize(ImVec2(660, 520), ImGuiCond_FirstUseEver);
        ImGui::Begin("PES 2016 - Mod Menu (injetado)");
        ImGui::Text("Device: %p   HWND: %p", (void*)dev, (void*)g_hwnd);
        ImGui::TextDisabled(
            "Insert abre/fecha. Setas + Enter navegam. Esc fecha.");
        ImGui::SeparatorText("Etapa 2: memoria ao vivo");

        // ---- Jogador / lesao -------------------------------------------------
        ImGui::SetNextItemWidth(190);
        ImGui::InputText("Nome do jogador", g_player_name,
                         sizeof(g_player_name));
        ImGui::SameLine();
        if (ImGui::Button("Procurar jogador")) player_search();
        if (g_player_found) {
            ImGui::Text("copias=%d   ID=%08X   lesao=%u",
                        g_player_copy_count, g_player_copies[0].id,
                        g_player_copies[0].injury);
            if (ImGui::Button("Curar lesao")) player_write_injury(0);
            ImGui::SameLine();
            if (ImGui::Button("Lesionar (teste)")) player_write_injury(44);
            ImGui::SameLine();
            if (ImGui::Button("Reverter lesao")) player_revert_injury();
            ImGui::SameLine();
            ImGui::TextDisabled("(leitura original guardada)");
        } else {
            ImGui::TextDisabled(
                "Digite o nome exato do jogador e procure.");
        }

        // ---- Dinheiro da Liga Master ----------------------------------------
        ImGui::SeparatorText("Dinheiro da Liga Master");
        ImGui::TextDisabled(
            "Digite o saldo do jogo (ex.: 27486800) e confirme com Enter.");
        ImGui::SetNextItemWidth(200);
        ImGui::InputText("Saldo atual", g_money_atual_buf,
                         sizeof(g_money_atual_buf),
                         ImGuiInputTextFlags_CharsDecimal);
        if (ImGui::IsItemDeactivatedAfterEdit()) money_search();
        ImGui::SameLine();
        if (ImGui::Button("Procurar saldo")) money_search();
        if (g_money_found) {
            ImGui::Text("enderecos=%d   na memoria=%.0f", g_money_count,
                        money_current() * (double)MONEY_SCALE);
            ImGui::SetNextItemWidth(200);
            ImGui::InputText("Novo saldo", g_money_novo_buf,
                             sizeof(g_money_novo_buf),
                             ImGuiInputTextFlags_CharsDecimal);
            if (ImGui::IsItemDeactivatedAfterEdit()) money_apply();
            ImGui::SameLine();
            if (ImGui::Button("Aplicar")) money_apply();
            ImGui::SameLine();
            if (ImGui::Button("Reverter")) money_revert();
        } else {
            ImGui::TextDisabled(
                "Informe o saldo que aparece no jogo e procure.");
        }

        ImGui::Separator();
        ImGui::TextDisabled("Nada e gravado sem apertar um botao.");
        ImGui::End();

        ImGui::Render();
        dev->SetStreamSource(0, NULL, 0, 0);
        dev->SetIndices(NULL);
        dev->SetVertexDeclaration(NULL);
        ImGui_ImplDX9_RenderDrawData(ImGui::GetDrawData());
    }

    return g_orig_EndScene(dev);
}

// Chamado depois que o jogo cria o device (CreateDevice ou CreateDeviceEx).
static void setup_device(HWND hFocusWindow, IDirect3DDevice9* dev) {
    if (!dev) return;
    g_hwnd = hFocusWindow;
    g_device = dev;
    void** vtbl = *(void***)g_device;
    if (patch_vtable_slot(vtbl, VTBL_DEV_ENDSCENE, (void*)hook_EndScene,
                          (void**)&g_orig_EndScene))
        logmsg("EndScene hookado in-place (idx %d, orig=%p)",
               VTBL_DEV_ENDSCENE, (void*)g_orig_EndScene);
    init_imgui(g_device, hFocusWindow);
}

static HRESULT STDMETHODCALLTYPE hook_CreateDevice(
    IDirect3D9* self, UINT Adapter, D3DDEVTYPE DeviceType, HWND hFocusWindow,
    DWORD BehaviorFlags, D3DPRESENT_PARAMETERS* pp,
    IDirect3DDevice9** ppDevice) {
    logmsg("hook_CreateDevice entrou (orig=%p this=%p)", (void*)g_orig_CreateDevice,
           (void*)self);
    HRESULT hr = g_orig_CreateDevice(self, Adapter, DeviceType, hFocusWindow,
                                     BehaviorFlags, pp, ppDevice);
    logmsg("CreateDevice hr=0x%08x hwnd=%p dev=%p", (unsigned)hr,
           (void*)hFocusWindow, (void*)(ppDevice ? *ppDevice : nullptr));
    if (SUCCEEDED(hr) && ppDevice && *ppDevice)
        setup_device(hFocusWindow, *ppDevice);
    return hr;
}

static HRESULT STDMETHODCALLTYPE hook_CreateDeviceEx(
    IDirect3D9Ex* self, UINT Adapter, D3DDEVTYPE DeviceType, HWND hFocusWindow,
    DWORD BehaviorFlags, D3DPRESENT_PARAMETERS* pp, D3DDISPLAYMODEEX* mode,
    IDirect3DDevice9Ex** ppDevice) {
    logmsg("hook_CreateDeviceEx entrou (orig=%p this=%p)",
           (void*)g_orig_CreateDeviceEx, (void*)self);
    HRESULT hr = g_orig_CreateDeviceEx(self, Adapter, DeviceType, hFocusWindow,
                                       BehaviorFlags, pp, mode, ppDevice);
    logmsg("CreateDeviceEx hr=0x%08x hwnd=%p dev=%p", (unsigned)hr,
           (void*)hFocusWindow, (void*)(ppDevice ? *ppDevice : nullptr));
    if (SUCCEEDED(hr) && ppDevice && *ppDevice)
        setup_device(hFocusWindow, (IDirect3DDevice9*)*ppDevice);
    return hr;
}

// ---------------------------------------------------------------------------
// Export: Direct3DCreate9 (intercepta a criacao do IDirect3D9)
// ---------------------------------------------------------------------------
typedef IDirect3D9*(WINAPI* PFN_D3DCreate9)(UINT);
static PFN_D3DCreate9 g_real_Create9 = nullptr;

extern "C" __declspec(dllexport) IDirect3D9* WINAPI
Direct3DCreate9_impl(UINT sdk) {
    logmsg("Direct3DCreate9(%u) chamado", sdk);
    if (!g_real_Create9) {
        g_real_Create9 = (PFN_D3DCreate9)real_proc("Direct3DCreate9");
    }
    if (!g_real_Create9) {
        logmsg("ERRO: Direct3DCreate9 real nao encontrado");
        return nullptr;
    }
    IDirect3D9* d3d = g_real_Create9(sdk);
    logmsg("Direct3DCreate9 -> %p", (void*)d3d);
    if (d3d && !g_safe_mode) {
        void** vtbl = *(void***)d3d;
        logmsg("vtable ptr = %p", (void*)vtbl);
        bool a = patch_vtable_slot(vtbl, VTBL_D3D9_CREATEDEVICE,
                                   (void*)hook_CreateDevice,
                                   (void**)&g_orig_CreateDevice);
        bool b = patch_vtable_slot(vtbl, VTBL_D3D9_CREATEDEVICEEX,
                                   (void*)hook_CreateDeviceEx,
                                   (void**)&g_orig_CreateDeviceEx);
        logmsg("vtable do IDirect3D9 patchada in-place "
               "(CreateDevice idx %d %s, CreateDeviceEx idx %d %s)",
               VTBL_D3D9_CREATEDEVICE, a ? "ok" : "FALHOU",
               VTBL_D3D9_CREATEDEVICEEX, b ? "ok" : "FALHOU");
    } else if (d3d) {
        logmsg("MODO SEGURO: vtable nao foi hookada");
    }
    return d3d;
}

// ---------------------------------------------------------------------------
// Exports D3DPERF_* (o jogo importa estas; repassamos para o DXVK)
// ---------------------------------------------------------------------------
typedef int(WINAPI* PFN_PERF_BEGIN)(D3DCOLOR, LPCWSTR);
typedef int(WINAPI* PFN_PERF_END)(void);
typedef void(WINAPI* PFN_PERF_MARKER)(D3DCOLOR, LPCWSTR);
typedef void(WINAPI* PFN_PERF_OPTIONS)(DWORD);

extern "C" __declspec(dllexport) int WINAPI
D3DPERF_BeginEvent_impl(D3DCOLOR col, LPCWSTR name) {
    static PFN_PERF_BEGIN fn = nullptr;
    if (!fn) fn = (PFN_PERF_BEGIN)real_proc("D3DPERF_BeginEvent");
    return fn ? fn(col, name) : 0;
}

extern "C" __declspec(dllexport) int WINAPI D3DPERF_EndEvent_impl(void) {
    static PFN_PERF_END fn = nullptr;
    if (!fn) fn = (PFN_PERF_END)real_proc("D3DPERF_EndEvent");
    return fn ? fn() : 0;
}

extern "C" __declspec(dllexport) void WINAPI
D3DPERF_SetMarker_impl(D3DCOLOR col, LPCWSTR name) {
    static PFN_PERF_MARKER fn = nullptr;
    if (!fn) fn = (PFN_PERF_MARKER)real_proc("D3DPERF_SetMarker");
    if (fn) fn(col, name);
}

extern "C" __declspec(dllexport) void WINAPI
D3DPERF_SetOptions_impl(DWORD opts) {
    static PFN_PERF_OPTIONS fn = nullptr;
    if (!fn) fn = (PFN_PERF_OPTIONS)real_proc("D3DPERF_SetOptions");
    if (fn) fn(opts);
}

// ---------------------------------------------------------------------------
// DllMain
// ---------------------------------------------------------------------------
BOOL WINAPI DllMain(HINSTANCE hinst, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        init_paths(hinst);
        DisableThreadLibraryCalls(hinst);
        logmsg("=== d3d9 proxy (mod menu) anexado ao jogo (safe_mode=%d) ===",
               g_safe_mode ? 1 : 0);
    }
    return TRUE;
}
