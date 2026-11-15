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
static char g_dir[MAX_PATH] = {0};
static DWORD g_t0 = 0;
static bool g_menu_open = false;
static bool g_imgui_ready = false;
static bool g_safe_mode = false;
static bool g_autoscan = false;
static bool g_autoscan_done = false;
static bool g_sem_msg = false;    // pular a mensagem "Estabelecendo..."
static HWND g_hwnd = nullptr;
static IDirect3DDevice9* g_device = nullptr;

// ---------------------------------------------------------------------------
// Log
// ---------------------------------------------------------------------------
static void init_paths(HMODULE self) {
    g_self = self;
    g_t0 = GetTickCount();
    char path[MAX_PATH] = {0};
    GetModuleFileNameA(self, path, MAX_PATH);
    char* slash = strrchr(path, '\\');
    if (!slash) slash = strrchr(path, '/');
    if (slash) *(slash + 1) = 0;
    snprintf(g_dir, sizeof(g_dir), "%s", path);
    snprintf(g_log_path, sizeof(g_log_path), "%smodmenu.log", path);
    char flag[MAX_PATH];
    snprintf(flag, sizeof(flag), "%smodmenu_nohook.txt", path);
    g_safe_mode = GetFileAttributesA(flag) != INVALID_FILE_ATTRIBUTES;
    snprintf(flag, sizeof(flag), "%smodmenu_autoscan.txt", path);
    g_autoscan = GetFileAttributesA(flag) != INVALID_FILE_ATTRIBUTES;
    snprintf(flag, sizeof(flag), "%smodmenu_sem_comunicacoes.txt", path);
    g_sem_msg = GetFileAttributesA(flag) != INVALID_FILE_ATTRIBUTES;
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
    uint8_t height;
    uint8_t weight;
};

// Estado por modo: ML e BL nao compartilham resultados de busca.
struct PlayerState {
    PlayerCopy copies[8];
    uint8_t orig[8];
    char name[32];
    int count;
    bool found;
};

enum ModoCarreira { MODO_ML = 0, MODO_BL = 1, MODO_COUNT = 2 };

static const char* modo_nome(int modo) {
    return modo == MODO_BL ? "BL" : "ML";
}

static char g_player_name[32] = "WARLISON";
static PlayerState g_player[MODO_COUNT] = {};
static int g_modo = MODO_ML;

// Aba visivel: 0 = Master League, 1 = Vida Futebolistica, 2 = Comunicacoes.
static int g_aba = 0;
static bool g_msg_reiniciar = false;    // aviso: settings.dat so na abertura

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
    if (!addr || !dst || !n || addr > UINTPTR_MAX - n) return false;
    MEMORY_BASIC_INFORMATION mbi;
    if (!VirtualQuery((LPCVOID)addr, &mbi, sizeof(mbi))) return false;
    if (mbi.State != MEM_COMMIT || !prot_readable(mbi.Protect)) return false;
    uintptr_t end = (uintptr_t)mbi.BaseAddress + mbi.RegionSize;
    if (addr + n > end) return false;
    memcpy(dst, (const void*)addr, n);
    return true;
}

static bool safe_write(uintptr_t addr, const void* src, size_t n) {
    if (!addr || !src || !n || addr > UINTPTR_MAX - n) return false;
    MEMORY_BASIC_INFORMATION mbi;
    if (!VirtualQuery((LPCVOID)addr, &mbi, sizeof(mbi))) return false;
    if (mbi.State != MEM_COMMIT || !prot_writable(mbi.Protect)) return false;
    uintptr_t end = (uintptr_t)mbi.BaseAddress + mbi.RegionSize;
    if (addr + n > end) return false;
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
static void player_search(PlayerState& st) {
    st.found = false;
    st.count = 0;
    // Os nomes no jogo sao gravados em maiusculas; aceita o que o usuario
    // digitar e normaliza o campo para maiusculas.
    for (char* p = g_player_name; *p; ++p)
        if (*p >= 'a' && *p <= 'z') *p = (char)(*p - 'a' + 'A');
    size_t nlen = strlen(g_player_name);
    if (nlen < 2) {
        logmsg("[%s] busca: nome muito curto", modo_nome(g_modo));
        return;
    }
    snprintf(st.name, sizeof(st.name), "%s", g_player_name);
    DWORD t0 = GetTickCount();
    uintptr_t hits[MAX_HITS];
    int nhits = scan_bytes(g_player_name, nlen, false, hits, MAX_HITS);
    logmsg("[%s] busca de '%s': %d ocorrencias", modo_nome(g_modo),
           g_player_name, nhits);

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
        cand[nc].height = altura;
        cand[nc].weight = peso;
        ++nc;
    }
    logmsg("[%s] registros validos: %d (%.1f s)", modo_nome(g_modo), nc,
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

    for (int i = 0; i < nc && st.count < 8; ++i) {
        if (melhor_id && cand[i].id != melhor_id) continue;
        st.copies[st.count] = {cand[i].base, cand[i].id, cand[i].injury,
                               cand[i].height, cand[i].weight};
        st.orig[st.count] = cand[i].injury;
        ++st.count;
    }
    st.found = st.count > 0;
    if (st.found)
        logmsg("[%s] jogador escolhido: ID=%08x copias=%d lesao=%d",
               modo_nome(g_modo), melhor_id, st.count, st.copies[0].injury);
}

static bool player_copy_matches(const PlayerState& st, const PlayerCopy& copy,
                                unsigned char* record = nullptr) {
    unsigned char current[PLAYER_RECORD_SIZE];
    if (!safe_read(copy.base, current, sizeof(current))) return false;

    size_t name_len = strlen(st.name);
    if (name_len < 2 || name_len >= PLAYER_NAME_LEN ||
        memcmp(current + PLAYER_NAME_OFFSET, st.name, name_len) != 0 ||
        current[PLAYER_NAME_OFFSET + name_len] != 0)
        return false;

    uint32_t id = 0;
    memcpy(&id, current + PLAYER_ID_OFFSET, sizeof(id));
    if (id != copy.id || current[PLAYER_HEIGHT_OFFSET] != copy.height ||
        current[PLAYER_WEIGHT_OFFSET] != copy.weight)
        return false;

    if (record) memcpy(record, current, sizeof(current));
    return true;
}

static void player_write_injury(PlayerState& st, uint8_t valor) {
    for (int i = 0; i < st.count; ++i) {
        uintptr_t addr = st.copies[i].base + PLAYER_INJURY_OFFSET;
        unsigned char record[PLAYER_RECORD_SIZE];
        if (!player_copy_matches(st, st.copies[i], record)) {
            logmsg("[%s] lesao copia %d: registro mudou desde a busca; ignorado",
                   modo_nome(g_modo), i);
            continue;
        }
        uint8_t antes = record[PLAYER_INJURY_OFFSET];
        if (!safe_write(addr, &valor, 1)) {
            logmsg("[%s] lesao copia %d: endereco nao gravavel",
                   modo_nome(g_modo), i);
            continue;
        }
        logmsg("[%s] lesao copia %d: %u -> %u (0x%08x)", modo_nome(g_modo), i,
               antes, valor, (unsigned)addr);
        st.copies[i].injury = valor;
    }
}

static void player_revert_injury(PlayerState& st) {
    for (int i = 0; i < st.count; ++i) {
        uintptr_t addr = st.copies[i].base + PLAYER_INJURY_OFFSET;
        uint8_t valor = st.orig[i];
        unsigned char record[PLAYER_RECORD_SIZE];
        if (!player_copy_matches(st, st.copies[i], record)) {
            logmsg("[%s] lesao copia %d: registro mudou desde a busca; "
                   "reversao ignorada", modo_nome(g_modo), i);
            continue;
        }
        if (record[PLAYER_INJURY_OFFSET] != st.copies[i].injury) {
            logmsg("[%s] lesao copia %d: valor atual mudou (%u, esperado %u); "
                   "reversao ignorada", modo_nome(g_modo), i,
                   record[PLAYER_INJURY_OFFSET], st.copies[i].injury);
            continue;
        }
        if (!safe_write(addr, &valor, 1)) {
            logmsg("[%s] lesao copia %d: endereco nao gravavel",
                   modo_nome(g_modo), i);
            continue;
        }
        logmsg("[%s] lesao copia %d revertida para %u (0x%08x)",
               modo_nome(g_modo), i, valor, (unsigned)addr);
        st.copies[i].injury = valor;
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
            agora != g_money_raw[i]) {
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
    if (g_money_pending) {
        logmsg("dinheiro: aguarde a validacao dos enderecos");
        return;
    }
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
        // So grava se o valor ainda for o ultimo que encontramos ou aplicamos.
        if (antes != g_money_raw[i]) {
            logmsg("dinheiro 0x%08x: valor mudou (%d, esperado %d), nao gravei",
                   (unsigned)addr, antes, g_money_raw[i]);
            continue;
        }
        if (!safe_write(addr, &novo, 4)) {
            logmsg("dinheiro 0x%08x: endereco nao gravavel", (unsigned)addr);
            continue;
        }
        logmsg("dinheiro 0x%08x: %d -> %d", (unsigned)addr, antes, novo);
        g_money_raw[i] = novo;
    }
}

static void money_revert() {
    if (g_money_pending) {
        logmsg("dinheiro: aguarde a validacao dos enderecos");
        return;
    }
    for (int i = 0; i < g_money_count; ++i) {
        int32_t atual = 0;
        if (!safe_read(g_money_addr[i], &atual, 4)) {
            logmsg("dinheiro 0x%08x: nao consegui ler para reverter",
                   (unsigned)g_money_addr[i]);
            continue;
        }
        if (atual != g_money_raw[i]) {
            logmsg("dinheiro 0x%08x: valor mudou (%d, esperado %d), "
                   "reversao ignorada", (unsigned)g_money_addr[i], atual,
                   g_money_raw[i]);
            continue;
        }
        if (!safe_write(g_money_addr[i], &g_money_antes[i], 4)) {
            logmsg("dinheiro 0x%08x: endereco nao gravavel",
                   (unsigned)g_money_addr[i]);
            continue;
        }
        logmsg("dinheiro 0x%08x revertido para %d", (unsigned)g_money_addr[i],
               g_money_antes[i]);
        g_money_raw[i] = g_money_antes[i];
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

// ---------------------------------------------------------------------------
// Seletor de modo: Master League x Vida Futebolistica (Rumo ao Estrelato)
// ---------------------------------------------------------------------------
// Cada modo guarda seu proprio resultado de busca (g_player[g_modo]); so as
// opcoes daquele tipo de carreira aparecem na tela.

// Painel do jogador: busca o registro pelo nome e oferece lesao.
// Usado pelos dois modos (no BL e o seu jogador; no ML, um jogador do elenco).
static void ui_player_section(const char* titulo) {
    PlayerState& st = g_player[g_modo];
    ImGui::SeparatorText(titulo);
    ImGui::SetNextItemWidth(190);
    bool enter = ImGui::InputText("Nome do jogador", g_player_name,
                                  sizeof(g_player_name),
                                  ImGuiInputTextFlags_EnterReturnsTrue);
    if (!enter && ImGui::IsItemDeactivatedAfterEdit()) enter = true;
    if (enter) player_search(st);
    ImGui::SameLine();
    if (ImGui::Button("Procurar jogador")) player_search(st);
    if (st.found) {
        ImGui::Text("copias=%d   ID=%08X   lesao=%u", st.count,
                    st.copies[0].id, st.copies[0].injury);
        if (ImGui::Button("Curar lesao")) player_write_injury(st, 0);
        ImGui::SameLine();
        if (ImGui::Button("Lesionar (teste)")) player_write_injury(st, 44);
        ImGui::SameLine();
        if (ImGui::Button("Reverter lesao")) player_revert_injury(st);
        ImGui::SameLine();
        ImGui::TextDisabled("(leitura original guardada)");
    } else {
        ImGui::TextDisabled("Digite o nome exato do jogador e procure.");
    }
}

// Dinheiro do clube: so existe na Master League.
static void ui_money_section() {
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
        ImGui::TextDisabled("Informe o saldo que aparece no jogo e procure.");
    }
}

// ---------------------------------------------------------------------------
// settings.dat: porta UDP manual
// ---------------------------------------------------------------------------
// O Settings.exe grava o arquivo como um dump cru do struct SettingsData (360
// bytes, magic "WECF").  O "UDP automatico" e o bit 5 do int32 em 0x08 e a
// porta fica no int32 em 0x24 (padrao 5739, ignorado quando o automatico esta
// ligado).  Com a porta manual em 0 o jogo nao faz o teste de conexao e a
// mensagem "Estabelecendo comunicacoes" nao segura a abertura.
static const long SETTINGS_TAM = 360;
static const uint32_t SETTINGS_FLAGS_OFF = 0x08;
static const uint32_t SETTINGS_PORTA_OFF = 0x24;
static const uint32_t SETTINGS_FLAG_AUTO_UDP = 0x20;
static const uint32_t SETTINGS_PORTA_PADRAO = 5739;

struct SettingsInfo {
    bool ok;
    uint32_t flags;
    uint32_t porta;
};

static bool settings_path(char* destino, size_t n) {
    char perfil[MAX_PATH] = {0};
    if (!GetEnvironmentVariableA("USERPROFILE", perfil, MAX_PATH)) return false;
    snprintf(destino, n,
             "%s\\Documents\\KONAMI\\Pro Evolution Soccer 2016\\settings.dat",
             perfil);
    return true;
}

static SettingsInfo settings_ler() {
    SettingsInfo info = {false, 0, 0};
    char caminho[MAX_PATH];
    if (!settings_path(caminho, sizeof(caminho))) return info;
    FILE* f = fopen(caminho, "rb");
    if (!f) return info;
    unsigned char buf[SETTINGS_TAM];
    size_t lidos = fread(buf, 1, sizeof(buf), f);
    fclose(f);
    if (lidos != sizeof(buf)) return info;
    if (memcmp(buf, "WECF", 4) != 0) return info;
    memcpy(&info.flags, buf + SETTINGS_FLAGS_OFF, 4);
    memcpy(&info.porta, buf + SETTINGS_PORTA_OFF, 4);
    info.ok = true;
    return info;
}

static bool settings_gravar(uint32_t flags, uint32_t porta) {
    char caminho[MAX_PATH];
    if (!settings_path(caminho, sizeof(caminho))) return false;
    FILE* f = fopen(caminho, "r+b");
    if (!f) return false;
    unsigned char buf[SETTINGS_TAM];
    size_t lidos = fread(buf, 1, sizeof(buf), f);
    if (lidos != sizeof(buf) || memcmp(buf, "WECF", 4) != 0) {
        fclose(f);
        return false;
    }
    memcpy(buf + SETTINGS_FLAGS_OFF, &flags, 4);
    memcpy(buf + SETTINGS_PORTA_OFF, &porta, 4);
    fseek(f, 0, SEEK_SET);
    bool ok = fwrite(buf, 1, sizeof(buf), f) == sizeof(buf);
    fclose(f);
    logmsg("settings: flags=0x%02x porta=%u (%s)", flags, porta, caminho);
    return ok;
}

static void settings_info_log(const SettingsInfo& info) {
    if (!info.ok) {
        logmsg("settings: settings.dat nao encontrado ou invalido");
        return;
    }
    logmsg("settings: auto_udp=%d porta=%u",
           (info.flags & SETTINGS_FLAG_AUTO_UDP) ? 1 : 0, info.porta);
}

// Aplicado no carregamento da dll, antes de o jogo ler o settings.dat.  O
// marcador ".aplicado" lembra que foi o mod quem alterou o arquivo, para o
// "reverter" nao mexer numa configuracao que o usuario ajustou na mao.
static void sem_msg_aplicar() {
    char marcador[MAX_PATH];
    char aplicado[MAX_PATH];
    snprintf(marcador, sizeof(marcador), "%smodmenu_sem_comunicacoes.txt",
             g_dir);
    snprintf(aplicado, sizeof(aplicado), "%smodmenu_sem_comunicacoes.aplicado",
             g_dir);
    bool quer = GetFileAttributesA(marcador) != INVALID_FILE_ATTRIBUTES;
    bool aplicado_antes = GetFileAttributesA(aplicado) != INVALID_FILE_ATTRIBUTES;
    SettingsInfo info = settings_ler();
    settings_info_log(info);

    if (quer) {
        if (info.ok && (info.flags & SETTINGS_FLAG_AUTO_UDP) == 0 &&
            info.porta == 0) {
            // Ja esta como o mod quer (talvez o jogo tenha salvo assim).
            if (!aplicado_antes) {
                FILE* f = fopen(aplicado, "wb");
                if (f) fclose(f);
            }
            return;
        }
        if (!info.ok) return;
        if (settings_gravar(info.flags & ~SETTINGS_FLAG_AUTO_UDP, 0)) {
            FILE* f = fopen(aplicado, "wb");
            if (f) fclose(f);
            logmsg("settings: mensagem de comunicacoes desativada");
        }
    } else if (aplicado_antes) {
        // Desfaz apenas o que o mod alterou: volta o automatico e a porta
        // padrao (5739), sem tocar no resto do arquivo.
        if (info.ok &&
            settings_gravar(info.flags | SETTINGS_FLAG_AUTO_UDP,
                            SETTINGS_PORTA_PADRAO)) {
            DeleteFileA(aplicado);
            logmsg("settings: mensagem de comunicacoes restaurada");
        }
    }
}

static void sem_msg_set(bool ligado) {
    char marcador[MAX_PATH];
    snprintf(marcador, sizeof(marcador), "%smodmenu_sem_comunicacoes.txt",
             g_dir);
    if (ligado) {
        FILE* f = fopen(marcador, "wb");
        if (f) fclose(f);
    } else {
        DeleteFileA(marcador);
    }
    g_sem_msg = ligado;
    g_msg_reiniciar = true;
    logmsg("settings: opcao de abertura %s (%s)", ligado ? "LIGADA" : "desligada",
           marcador);
}

static void ui_comunicacoes_section() {
    ImGui::SeparatorText("Abertura mais rapida (recomendado)");
    ImGui::TextWrapped(
        "Na abertura o jogo faz um teste de conexao (UDP) com os servidores "
        "online da Konami e a mensagem \"Estabelecendo comunicacoes\" fica "
        "esperando esse teste por 10 a 15 segundos.  No Settings.exe isso se "
        "resolve na aba Online: desmarcar \"Automatico\" e por porta 0.  Este "
        "botao faz o mesmo no settings.dat.");
    ImGui::Spacing();

    static SettingsInfo info = {false, 0, 0};
    static DWORD lido_em = 0;
    if (GetTickCount() - lido_em > 500) {
        info = settings_ler();
        lido_em = GetTickCount();
    }
    if (!info.ok) {
        ImGui::TextColored(ImVec4(1.0f, 0.6f, 0.4f, 1.0f),
                           "settings.dat nao encontrado ou invalido.");
    } else if (info.flags & SETTINGS_FLAG_AUTO_UDP) {
        ImGui::TextDisabled("Porta UDP automatica (o jogo espera o teste).");
    } else {
        ImGui::TextColored(ImVec4(0.4f, 0.9f, 0.4f, 1.0f),
                           "Porta UDP manual: %u (sem espera do teste).",
                           info.porta);
    }
    if (ImGui::Button(g_sem_msg
                          ? "Voltar a espera normal (reverter)"
                          : "Encurtar a mensagem \"Estabelecendo comunicacoes\""))
        sem_msg_set(!g_sem_msg);
    if (g_msg_reiniciar) {
        ImGui::Spacing();
        ImGui::TextColored(ImVec4(1.0f, 0.85f, 0.3f, 1.0f),
                           "Feche e abra o jogo.  O settings.dat so e lido na "
                           "abertura.");
    }
}

// ---------------------------------------------------------------------------
// Teclado modal: o jogo le teclas por DirectInput (polling), que nao passa
// pelo WndProc. Interceptamos a criacao dos objetos do jogo e zeramos o estado
// do teclado no GetDeviceState enquanto o menu esta aberto.
// ---------------------------------------------------------------------------
typedef HRESULT(STDMETHODCALLTYPE* DiGetDeviceStateFn)(void*, DWORD, void*);
typedef HRESULT(STDMETHODCALLTYPE* DiCreateDeviceFn)(void*, const void*,
                                                     void**, void*);
typedef HRESULT(WINAPI* Di8CreateFn)(HINSTANCE, DWORD, const void*, void**,
                                     void*);
typedef HHOOK(WINAPI* SetWindowsHookExWFn)(int, HOOKPROC, HINSTANCE, DWORD);

struct DiVtable {
    void** vt;
    DiGetDeviceStateFn get_state;
};
static DiVtable g_di_vt[4] = {};
static int g_di_vt_count = 0;
static DiCreateDeviceFn g_create_device_orig = nullptr;
static Di8CreateFn g_di8_create_real = nullptr;

// O jogo instala um hook global de teclado (WH_KEYBOARD_LL). Trocamos o
// procedimento dele pelo nosso: com o menu aberto, as teclas nao chegam ao
// jogo; com o menu fechado, repassamos para o procedimento original.
static SetWindowsHookExWFn g_set_hook_orig = nullptr;
static HOOKPROC g_jogo_kbd_proc = nullptr;
static int g_jogo_kbd_tipo = 0;

static LRESULT CALLBACK hook_teclado_jogo(int code, WPARAM wp, LPARAM lp) {
    if (g_menu_open) return CallNextHookEx(nullptr, code, wp, lp);
    if (g_jogo_kbd_proc) return g_jogo_kbd_proc(code, wp, lp);
    return CallNextHookEx(nullptr, code, wp, lp);
}

static HHOOK WINAPI hook_set_windows_hook(int id, HOOKPROC proc, HINSTANCE h,
                                          DWORD tid) {
    if (!g_set_hook_orig) return nullptr;
    if (proc && (id == WH_KEYBOARD_LL || id == WH_KEYBOARD)) {
        g_jogo_kbd_proc = proc;
        g_jogo_kbd_tipo = id;
        logmsg("teclado: hook do jogo interceptado (tipo=%d)", id);
        return g_set_hook_orig(id, hook_teclado_jogo, h, tid);
    }
    return g_set_hook_orig(id, proc, h, tid);
}

static bool pointer_in_module(const void* p, HMODULE h) {
    if (!h || !p) return false;
    const IMAGE_DOS_HEADER* dos = (const IMAGE_DOS_HEADER*)h;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return false;
    const IMAGE_NT_HEADERS* nt =
        (const IMAGE_NT_HEADERS*)((const BYTE*)h + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return false;
    uintptr_t base = (uintptr_t)h;
    uintptr_t end = base + nt->OptionalHeader.SizeOfImage;
    uintptr_t a = (uintptr_t)p;
    return a >= base && a < end;
}

static void patch_slot(void** vt, int idx, void* fn) {
    DWORD old = 0;
    if (VirtualProtect(&vt[idx], sizeof(void*), PAGE_READWRITE, &old)) {
        vt[idx] = fn;
        VirtualProtect(&vt[idx], sizeof(void*), old, &old);
    }
}

static HRESULT STDMETHODCALLTYPE hook_di_get_state(void* self, DWORD cb,
                                                   void* data) {
    void** vt = self ? *(void***)self : nullptr;
    DiGetDeviceStateFn orig = nullptr;
    for (int i = 0; i < g_di_vt_count; ++i)
        if (g_di_vt[i].vt == vt) orig = g_di_vt[i].get_state;
    if (!orig) return E_FAIL;
    HRESULT hr = orig(self, cb, data);
    // Teclado tem 256 bytes de estado; mouse/joystick tem outros tamanhos.
    if (SUCCEEDED(hr) && g_menu_open && data && cb == 256)
        memset(data, 0, 256);
    return hr;
}

// Chamado para cada dispositivo criado pelo jogo. A vtable e compartilhada,
// entao basta interceptar uma vez por vtable.
static void hook_device(void* dev) {
    if (!dev) return;
    void** vt = *(void***)dev;
    for (int i = 0; i < g_di_vt_count; ++i)
        if (g_di_vt[i].vt == vt) return;
    HMODULE h = GetModuleHandleA("dinput8.dll");
    void* orig = vt[9];
    if (!pointer_in_module(orig, h)) {
        logmsg("teclado: GetDeviceState inesperado (%p); sem bloqueio", orig);
        return;
    }
    if (g_di_vt_count >= 4) return;
    g_di_vt[g_di_vt_count].vt = vt;
    g_di_vt[g_di_vt_count].get_state = (DiGetDeviceStateFn)orig;
    ++g_di_vt_count;
    patch_slot(vt, 9, (void*)hook_di_get_state);
    logmsg("teclado: GetDeviceState interceptado (vtable=%p)", (void*)vt);
}

static HRESULT STDMETHODCALLTYPE hook_di_create_device(void* self,
                                                       const void* guid,
                                                       void** out, void* outer) {
    if (!g_create_device_orig) return E_FAIL;
    HRESULT hr = g_create_device_orig(self, guid, out, outer);
    if (SUCCEEDED(hr) && out && *out) hook_device(*out);
    return hr;
}

// Wrapper do DirectInput8Create (patch na IAT do executavel).
static HRESULT WINAPI hook_di8_create(HINSTANCE hinst, DWORD ver,
                                      const void* iid, void** out, void* outer) {
    if (!g_di8_create_real) {
        HMODULE h = LoadLibraryA("dinput8.dll");
        if (!h) return E_FAIL;
        g_di8_create_real =
            (Di8CreateFn)GetProcAddress(h, "DirectInput8Create");
        if (!g_di8_create_real) return E_FAIL;
    }
    HRESULT hr = g_di8_create_real(hinst, ver, iid, out, outer);
    if (FAILED(hr) || !out || !*out) return hr;
    HMODULE h = GetModuleHandleA("dinput8.dll");
    void** vt = *(void***)*out;
    void* orig = vt[3];   // IDirectInput8: CreateDevice (indice 3)
    if (!pointer_in_module(orig, h)) {
        logmsg("teclado: CreateDevice inesperado (%p); sem bloqueio", orig);
        return hr;
    }
    if (!g_create_device_orig) {
        g_create_device_orig = (DiCreateDeviceFn)orig;
        patch_slot(vt, 3, (void*)hook_di_create_device);
        logmsg("teclado: DirectInput interceptado");
    }
    return hr;
}

// Troca o ponteiro de uma funcao importada na IAT do executavel.
static void* patch_iat(HMODULE exe, const char* dll_name, const char* func,
                       void* hook) {
    if (!exe) return nullptr;
    const IMAGE_DOS_HEADER* dos = (const IMAGE_DOS_HEADER*)exe;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return nullptr;
    const IMAGE_NT_HEADERS* nt =
        (const IMAGE_NT_HEADERS*)((const BYTE*)exe + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return nullptr;
    const IMAGE_DATA_DIRECTORY& dir =
        nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dir.VirtualAddress) return nullptr;
    IMAGE_IMPORT_DESCRIPTOR* imp =
        (IMAGE_IMPORT_DESCRIPTOR*)((BYTE*)exe + dir.VirtualAddress);
    for (; imp->Name; ++imp) {
        const char* nome = (const char*)((BYTE*)exe + imp->Name);
        if (_stricmp(nome, dll_name) != 0) continue;
        IMAGE_THUNK_DATA* thunk = (IMAGE_THUNK_DATA*)(
            (BYTE*)exe + (imp->OriginalFirstThunk ? imp->OriginalFirstThunk
                                                  : imp->FirstThunk));
        IMAGE_THUNK_DATA* iat =
            (IMAGE_THUNK_DATA*)((BYTE*)exe + imp->FirstThunk);
        for (; thunk->u1.Function; ++thunk, ++iat) {
            if (IMAGE_SNAP_BY_ORDINAL(thunk->u1.Ordinal)) continue;
            const IMAGE_IMPORT_BY_NAME* ibn =
                (const IMAGE_IMPORT_BY_NAME*)((BYTE*)exe +
                                              thunk->u1.AddressOfData);
            if (strcmp((const char*)ibn->Name, func) != 0) continue;
            DWORD old = 0;
            void* original = (void*)iat->u1.Function;
            if (VirtualProtect(&iat->u1.Function, sizeof(void*),
                               PAGE_READWRITE, &old)) {
                iat->u1.Function = (ULONG_PTR)hook;
                VirtualProtect(&iat->u1.Function, sizeof(void*), old, &old);
                return original;
            }
            return nullptr;
        }
        return nullptr;
    }
    return nullptr;
}

// Instalado no DllMain: o jogo ainda nao criou os dispositivos de entrada.
static void install_input_hooks() {
    static bool done = false;
    if (done) return;
    done = true;
    HMODULE exe = GetModuleHandleA(nullptr);
    void* orig =
        patch_iat(exe, "DINPUT8.dll", "DirectInput8Create", (void*)hook_di8_create);
    if (orig) {
        g_di8_create_real = (Di8CreateFn)orig;
        logmsg("teclado: DirectInput8Create interceptado");
    } else {
        logmsg("teclado: DirectInput8Create nao esta na IAT do jogo");
    }
    void* sethook = patch_iat(exe, "USER32.dll", "SetWindowsHookExW",
                              (void*)hook_set_windows_hook);
    if (sethook) {
        g_set_hook_orig = (SetWindowsHookExWFn)sethook;
        logmsg("teclado: SetWindowsHookExW interceptado");
    } else {
        logmsg("teclado: SetWindowsHookExW nao esta na IAT do jogo");
    }
}


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

    // Raw input nao passa pelo bloqueio de mensagens: com o menu aberto,
    // esvazia a fila para o jogo nao receber as teclas.
    if (msg == WM_INPUT) {
        BYTE raw[256];
        UINT tam = sizeof(raw);
        GetRawInputData((HRAWINPUT)lp, RID_INPUT, raw, &tam,
                        sizeof(RAWINPUTHEADER));
        return 0;
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
            player_search(g_player[g_modo]);
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
        ImGui::SetNextWindowSize(ImVec2(660, 430), ImGuiCond_FirstUseEver);
        ImGui::Begin("PES 2016 - Mod Menu (injetado)");
        ImGui::Text("Device: %p   HWND: %p", (void*)dev, (void*)g_hwnd);
        ImGui::TextDisabled(
            "Insert abre/fecha. Setas + Enter navegam. Esc fecha.");

        // ---- Seletor de aba -------------------------------------------------
        // Cada aba mostra so as opcoes daquele assunto.
        ImGui::Separator();
        if (ImGui::Selectable("Master League", g_aba == 0, 0, ImVec2(150, 0))) {
            g_aba = 0;
            g_modo = MODO_ML;
        }
        ImGui::SameLine();
        if (ImGui::Selectable("Vida Futebolistica", g_aba == 1, 0,
                              ImVec2(175, 0))) {
            g_aba = 1;
            g_modo = MODO_BL;
        }
        ImGui::SameLine();
        if (ImGui::Selectable("Comunicacoes", g_aba == 2, 0, ImVec2(140, 0)))
            g_aba = 2;
        if (g_aba != 2) {
            ImGui::SameLine();
            ImGui::TextDisabled(g_aba == 0 ? "(Liga Master)"
                                           : "(Rumo ao Estrelato)");
        }
        ImGui::Separator();
        ImGui::Spacing();

        if (g_aba == 0) {
            ui_player_section("Jogador do elenco");
            ui_money_section();
        } else if (g_aba == 1) {
            ui_player_section("Seu jogador");
            ImGui::Spacing();
            ImGui::TextDisabled(
                "No Vida Futebolistica nao existe dinheiro de clube:");
            ImGui::TextDisabled(
                "use as opcoes do jogador acima.");
        } else {
            ui_comunicacoes_section();
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
        sem_msg_aplicar();
        if (g_safe_mode) {
            logmsg("MODO SEGURO: hooks de Direct3D e entrada nao instalados");
        } else {
            install_input_hooks();
        }
    }
    return TRUE;
}
