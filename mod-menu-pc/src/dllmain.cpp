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
    // Esc fecha o menu (e nao chega ao jogo).
    if (g_menu_open && msg == WM_KEYDOWN && wp == VK_ESCAPE) {
        g_menu_open = false;
        logmsg("menu fechado (Esc)");
        return 1;
    }
    if (g_menu_open && ImGui_ImplWin32_WndProcHandler(hwnd, msg, wp, lp))
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
    }
    antes = agora;

    if (g_menu_open && g_imgui_ready) {
        ImGui::GetIO().MouseDrawCursor = true;
        ImGui_ImplDX9_NewFrame();
        ImGui_ImplWin32_NewFrame();
        ImGui::NewFrame();

        ImGui::SetNextWindowPos(ImVec2(40, 40), ImGuiCond_FirstUseEver);
        ImGui::SetNextWindowSize(ImVec2(460, 240), ImGuiCond_FirstUseEver);
        ImGui::Begin("PES 2016 - Mod Menu (injetado)");
        ImGui::Text("Injecao/hook D3D9 funcionando!");
        ImGui::Text("Device: %p   HWND: %p", (void*)dev, (void*)g_hwnd);
        ImGui::Separator();
        static int cliques = 0;
        if (ImGui::Button("Gravar teste no log")) {
            ++cliques;
            logmsg("botao de teste acionado dentro do menu (%d)", cliques);
        }
        ImGui::SameLine();
        ImGui::Text("acionamentos: %d", cliques);
        ImGui::TextDisabled(
            "Insert abre/fecha. Setas + Enter navegam. Esc fecha.");
        ImGui::TextDisabled("Etapa 1: sem alterar o jogo.");
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
