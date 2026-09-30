# Phase 9A：最終合成畫面擷取（`video.composite.capture`）

> 對應：Modern DOSBox Runtime Master Plan v2 — D6（可觀測性）、S6.1、S6.3
> 狀態：C1–C7 已實作（`direct3d`、`surface`）；C8（OpenGL）未實作。實作與設計的差異見 §12
> Source 基準：`dosbox-src` submodule @ `00bacfd7c31dccab5b8570f569b12c42d2783f0c`（以下行號皆指此 commit）

---

## 1. 目的

現有的 `capture_frame`（Phase 7A）擷取的是 **scaler 之前的 guest 原生畫面**，資料來源是 `scalerSourceCacheBuffer`（`render.cpp:528`）。這一層看不到：

- backend 的放大與濾鏡（bilinear／nearest、aspect correction）
- D3D／OpenGL pixel shader
- letterbox／pillarbox 與 viewport 位置
- 未來 Modern Runtime 在 scaling 之後疊上去的 HiRes 文字、Modern UI、HD Cursor

`capture_composite` 要擷取的是 **backend 即將 present 到螢幕的那一張 back buffer**，並附上完整的座標幾何資訊，讓 Agent 可以：

1. 驗收 HiRes overlay（M6 之後的每個畫面相關 Step）
2. 直接取得 viewport 與縮放參數（S6.1 的資料來源）
3. 用同一個 emulated frame 對照 `capture_frame`，確認 overlay 沒有污染 DOS 影像

## 2. 非目標

| 不做 | 理由 |
|---|---|
| 擷取 Windows 視窗或桌面（PrintWindow、BitBlt、DXGI Desktop Duplication） | 與 Phase 7A 相同原則：不可受其他視窗遮擋影響、不依賴 host 桌面 |
| 擷取 host 滑鼠游標 | Windows 游標由 OS 繪製，不在 back buffer 裡。Guest 自己畫的 software cursor 會自然包含在內 |
| 串流、錄影 | 一次請求只回傳一個 frame |
| 支援所有 backend | 第一版只支援 `direct3d` 與 `surface`；`opengl*` 列為 P1（見 §5.3） |
| 暫停 guest | 與 `capture_frame` 相同，不 pause |

## 3. Source 調查結論

| # | 事實 | 位置 | 標記 |
|---|---|---|---|
| F1 | Windows + `C_DIRECT3D` 的 build，`output=default` 會解析為 `direct3d`（D3D9） | `output_tools.cpp:75-91` | Observed（source） |
| F2 | 每個 frame 的 present 路徑：`RENDER_EndUpdate()` → `GFX_EndUpdate()` → 依 `sdl.desktop.type` 分派到各 backend | `render.cpp:476`、`sdlmain.cpp:3305, 3348` | Observed |
| F3 | **D3D9 在獨立的 worker thread 上 present**（`D3D_THREAD 1`）。`UnlockTexture(changed)` 只送出 `D3D_UNLOCK` 指令就返回，實際的 `D3DSwapBuffers()` 在 worker thread 執行 | `direct3d.h:28`、`direct3d.cpp:203, 317-329, 709` | Observed |
| F4 | D3D9 在 `EndScene()` 之後、`Present()` 之前，back buffer 內容是完整的最終畫面（含 pixel shader 的最後一個 pass） | `direct3d.cpp:862-864` | Observed |
| F5 | `SwapEffect = D3DSWAPEFFECT_DISCARD`：`Present()` 之後 back buffer 內容未定義，**必須在 Present 之前讀回** | `direct3d.cpp:137` | Observed |
| F6 | 已有可沿用的讀回範例：`GetBackBuffer` + `CreateOffscreenPlainSurface(D3DPOOL_SYSTEMMEM)` + `GetRenderTargetData` | `direct3d.cpp:659-700`（`UpdateRectToSDLSurface`） | Observed |
| F7 | Back buffer 格式等於桌面格式（`d3ddm.Format`），一般是 `D3DFMT_X8R8G8B8`；`bpp16` 時為 16-bit | `direct3d.cpp:383` | Observed（實際值需 runtime 確認） |
| F8 | 畫面沒有任何變化時，`RENDER_EndUpdate()` 只在 `RENDER_GetForceUpdate()` 為真時才呼叫 `GFX_EndUpdate(nullptr)`；註解說明這只對 Direct3D 有效 | `render.cpp:543-546` | Observed |
| F9 | OpenGL 在沒有變化的行時會提早 return，不會 swap（`changedLines[0] == sdl.draw.height`，或 `changedLines == NULL` 走 `else return`） | `output_opengl.cpp:1066-1110` | Observed |
| F10 | Viewport（遊戲影像在 back buffer 中的位置）是 `sdl.clip`；aspect correction 由 `aspectCorrectFitClip()` 算進 clip | `output_direct3d.cpp:178-190` | Observed |
| F11 | 現有 `capture_frame` 的請求模式：socket thread 排入佇列 → 渲染點取出 → 透過 `conn->cv` 回傳；timeout 5 秒；payload 上限 8 MiB | `debug_ai.cpp:112-113, 1285-1320, 1568-1606, 3616-3690` | Observed |
| F12 | `capture_frame` 對 mode 13h 回報 640×400（DOSBox-X 在 render 層做 pixel doubling） | `ai/dosbox_client.py` 的 `get_mouse_capture()` docstring | Observed（既有文件） |

**結論**：擷取點必須放在各 backend 的「合成完成、present 之前」。D3D9 的擷取發生在 worker thread，而不是 emulator thread，這是本設計和 Phase 7A 最大的差異。

## 4. 架構

### 4.1 Present Hook 接點（同時為 Modern Runtime 預留）

新增一個與 backend 無關的接點。本 Phase 只實作擷取；Modern Runtime 在 M6 會在同一個位置、**擷取之前**插入 overlay 繪製：

```text
D3D9 worker thread — D3DSwapBuffers()
  BeginScene()
  DrawPrimitive(DOS 影像 quad／shader passes)
  ┌─ [M6 之後] PRESENT_Hook_DrawOverlays()   ← 在 scene 內；本 Phase 不實作
  EndScene()
  ┌─ PRESENT_Hook_BeforePresent(ctx)          ← 本 Phase：composite capture 在這裡
  Present()
```

這個順序保證了：**擷取到的就是玩家實際看到的畫面**，包含未來所有 overlay 層。

```cpp
// include/present_hook.h（新增）
struct PresentContext {
    const char *backend;          // "direct3d" | "surface" | "opengl" ...
    uint64_t    render_seq;       // 此次 present 對應的 RENDER_EndUpdate 序號（§4.3）
    uint32_t    bb_width, bb_height;           // back buffer 尺寸
    int32_t     clip_x, clip_y, clip_w, clip_h;// sdl.clip：viewport
    uint32_t    draw_width, draw_height;       // sdl.draw：送進 backend 的 texture 尺寸
};

// 由各 backend 在「合成完成、present 之前」呼叫。
// 沒有待處理請求時，成本只有一次 relaxed atomic load。
void PRESENT_Hook_BeforePresent(const PresentContext &ctx, IPresentReadback &rb);
```

`IPresentReadback` 由各 backend 實作，負責把目前的 back buffer 讀回成 RGBA8888：

```cpp
struct IPresentReadback {
    // 讀回整張 back buffer 或指定矩形，輸出緊密排列的 RGBA8888。失敗回傳 false。
    virtual bool ReadRGBA8888(int x, int y, int w, int h, std::vector<uint8_t> &out) = 0;
};
```

### 4.2 執行緒模型

| 動作 | Thread | 說明 |
|---|---|---|
| 解析參數、排入請求 | Socket thread | 與 Phase 7A 相同 |
| **Arm**：為請求指定 `target_render_seq`；需要時擷取 source frame；設定 force-present | Emulator thread（`RENDER_EndUpdate`） | 見 §4.3 |
| **Readback**：讀回 back buffer 並複製成 RGBA | Present thread（D3D9 為 worker thread；surface 為 emulator thread） | 只做複製，**不做 PNG 編碼** |
| 裁切、縮放、PNG 編碼、base64、送出回應 | Socket thread（等待中的那一個） | 避免 PNG 編碼卡住 render thread |

共用狀態一律用 `std::mutex` 加上 `std::atomic<bool> g_compositePending` 保護。Present thread 上**禁止**讀寫任何 emulator 狀態（CPU、記憶體、PIC），需要的資訊全部由 Arm 階段放進請求結構。

### 4.3 Frame 對應（render_seq）

1. `RENDER_EndUpdate()` 每次被呼叫都遞增 `g_renderSeq`（emulator thread）。
2. Arm 階段：把請求的 `target_render_seq` 設為目前的 seq，並記錄 `captured_at_emulated_ms = PIC_FullIndex()`。若 `include_source=true`，此時用 Phase 7A 既有的 `UnpackFrameToRGBA8888()` 擷取 source frame。
3. D3D9：在 `UnlockTexture(changed)` 送出 `D3D_UNLOCK` 時，把 seq 存進 `CDirect3D` 的成員；worker thread 在 `D3DSwapBuffers()` 中放進 `PresentContext.render_seq`。依 F3，同一時間最多只有一個未完成的指令，因此 seq 與畫面一一對應。
4. Readback 只接受 `ctx.render_seq >= target_render_seq` 的 present。回應中同時回報 `target_render_seq` 與實際的 `presented_render_seq`；兩者相等時 `source_frame_match=true`。

### 4.4 靜止畫面的 force-present

依 F8、F9，畫面沒有變化時可能完全不 present，請求就會一直 timeout。

- **D3D9**：有待處理請求時，讓 `render.cpp:546` 的條件也成立：
  ```cpp
  if (RENDER_GetForceUpdate() || DEBUG_AI_CompositeCaptureWantsPresent()) GFX_EndUpdate(nullptr);
  ```
  **不可以修改 `render.forceUpdate` 本身**（shader 會用到）。
- **surface**：`sdl.surface` 在 present 之後仍保有內容，可以直接讀回，不需要 force。
- **OpenGL**（P1）：`GFX_EndUpdate(nullptr)` 不會 swap（F9）。需要改成一次性的 full redraw，實作前必須先驗證（Unknown）。

## 5. 各 Backend 實作

### 5.1 `direct3d`（D3D9）— P0，預設 backend

- 呼叫點：`CDirect3D::D3DSwapBuffers()` 中 `EndScene()` 之後、`Present()` 之前（`direct3d.cpp:862-864`）。
- 讀回：沿用 F6 的模式：`GetBackBuffer` → `GetRenderTargetData` → system-memory surface → `LockRect`。
- System-memory surface 在第一次擷取時建立並快取；back buffer 尺寸或格式改變（resize、全螢幕切換）時重建。`DestroyD3D()` 時釋放。
- 格式轉換：

| Back buffer 格式 | 記憶體排列 | 轉成 RGBA8888 |
|---|---|---|
| `D3DFMT_X8R8G8B8` / `A8R8G8B8` | B, G, R, X/A | R=b[2], G=b[1], B=b[0], **A=255**（忽略 X/A） |
| `D3DFMT_R5G6B5`（`bpp16`） | 16-bit | 沿用 Phase 7A 的 565 解包，並注意 RGB 順序 |
| `D3DFMT_X1R5G5B5` | 16-bit | 沿用 555 解包 |
| 其他 | — | 回傳 `COMPOSITE_UNSUPPORTED_FORMAT` |

- `d3dpp.MultiSampleType` 若不是 `D3DMULTISAMPLE_NONE`，`GetRenderTargetData` 會失敗；必須先 `StretchRect` 到非 multisample 的 render target。先在 runtime 確認實際值；是 NONE 就不處理（S0.3 一併記錄）。
- Device lost（`deviceLost == true`）：這一輪不讀回，請求保留到下一次成功的 present，或直到 timeout 後回傳 `COMPOSITE_DEVICE_LOST`。

### 5.2 `surface` — P0，作為參考實作

- 呼叫點：`OUTPUT_SURFACE_EndUpdate()` 中所有 `SDL_UpdateWindowSurface` / `SDL_Flip` / `SDL_UpdateRects` 之前（`output_surface.cpp:687-773`，共有多個分支，每個分支都要接）。
- 讀回：`sdl.surface->pixels`，依 `sdl.surface->format` 轉成 RGBA；需要時 `SDL_LockSurface`。
- 在 emulator thread 上執行，最容易驗證，適合用來先驗證整條管線。

### 5.3 `opengl` / `openglnb` / `openglpp` — P1

- 呼叫點：`glCallList` / `glDrawArrays` 之後、`SDL_GL_SwapBuffers()` 之前（`output_opengl.cpp:1041, 1149`）。
- 讀回：`glReadBuffer(GL_BACK)` + `glReadPixels(..., GL_BGRA, GL_UNSIGNED_BYTE)`；**OpenGL 的原點在左下角，必須垂直翻轉**。
- 必須先解決 §4.4 的 force-present 問題，才能宣告支援。

### 5.4 其他 backend

`ttf`、`gamelink`、`direct3d11`、`metal`：回傳 `COMPOSITE_UNSUPPORTED_BACKEND`，訊息中列出目前的 backend 與支援清單。**不可以回退成 `capture_frame` 的結果**，否則 Agent 會誤以為看到的是最終畫面。

## 6. Bridge API

### 6.1 Request

```text
method: video.composite.capture
params:
{
  "format":         "png" | "rgba",          // 必填
  "crop":           "viewport" | "full",     // 預設 "viewport"
  "rect":           {"x","y","w","h"} | null,// output px，相對於 back buffer；與 crop/game_rect 互斥
  "game_rect":      {"x","y","w","h"} | null,// guest 原生座標（例如 320×200 空間），由 bridge 換算成 output px
  "max_width":      integer | null,          // 沿用 Phase 7A：nearest-neighbor 縮小、保持比例
  "max_height":     integer | null,
  "include_source": boolean                  // 預設 false；true 時一併回傳同一 frame 的 capture_frame 影像
}
```

`game_rect` 換算（只使用 bridge 回報的幾何資料，不猜）：

```text
out_x = clip_x + floor(gx       * clip_w / native_w)
out_y = clip_y + floor(gy       * clip_h / native_h)
out_r = clip_x + ceil ((gx+gw)  * clip_w / native_w)
out_b = clip_y + ceil ((gy+gh)  * clip_h / native_h)
```

`native_w`／`native_h` 取自 `render.src.width/height` 扣除 `dblw`／`dblh` 之後的值（mode 13h 為 320×200）。

### 6.2 Result

```jsonc
{
  "frame_id": 42,                       // 與 capture_frame 共用同一個遞增計數器
  "backend": "direct3d",
  "target_render_seq": 18230,
  "presented_render_seq": 18230,
  "source_frame_match": true,
  "captured_at_emulated_ms": 91234,
  "layers": ["dos_image"],              // M6 之後會出現 "modern_overlay"、"modern_cursor"
  "width": 1440, "height": 1080,        // 回傳影像的實際尺寸（裁切與縮放之後）
  "crop_rect": {"x":240,"y":0,"w":1440,"h":1080},  // 實際裁切範圍（output px）
  "scaled": false,
  "geometry": {
    "backbuffer":   {"w":1920,"h":1080},
    "viewport":     {"x":240,"y":0,"w":1440,"h":1080},   // sdl.clip
    "draw":         {"w":640,"h":400},                    // sdl.draw
    "render_src":   {"w":640,"h":400},                    // 與 capture_frame 相同
    "guest_native": {"w":320,"h":200},
    "scale":        {"x":4.5,"y":5.4},                    // viewport / guest_native
    "aspect_correction": true,
    "fullscreen": false,
    "pixel_shader": "none"               // D3D pixel shader 檔名；沒有時為 "none"
  },
  "pixel_format": "rgba8888",
  "png_base64": "...",                  // format=rgba 時為 "rgba_base64"
  "source": {                           // 只在 include_source=true 時出現
    "width": 640, "height": 400,
    "png_base64": "..."
  }
}
```

### 6.3 錯誤碼

| Code | 條件 | 既有／新增 |
|---|---|---|
| `INVALID_PARAMETER` | 參數型別錯誤；`rect`／`game_rect`／`crop` 同時指定 | 既有 |
| `CROP_OUT_OF_BOUNDS` | 換算後的矩形超出 back buffer，或寬高 ≤ 0 | 新增 |
| `COMPOSITE_UNSUPPORTED_BACKEND` | 目前 backend 不支援（訊息含 backend 名稱與支援清單） | 新增 |
| `COMPOSITE_UNSUPPORTED_FORMAT` | Back buffer 格式無法轉換 | 新增 |
| `COMPOSITE_DEVICE_LOST` | 等待期間 D3D device 一直處於 lost 狀態 | 新增 |
| `EXECUTION_TIMEOUT` | 5 秒內沒有符合條件的 present（例如 guest 停在 breakpoint、視窗最小化） | 既有 |
| `FRAME_TOO_LARGE` | 編碼後超過 8 MiB；附 `suggested_max_width/height` | 既有 |

**Payload 注意**：1920×1080 的 `rgba` 為 8,294,400 bytes，剛好在 8 MiB 以內；2560×1440 以上的 `rgba` 一定會超過上限。Agent 應以 `png` 為預設，並盡量使用 `crop` 或 `game_rect`。

## 7. Python Client 與 MCP Tool

### 7.1 `ai/dosbox_client.py`

```python
def capture_composite(self, format="png", crop="viewport", rect=None,
                      game_rect=None, max_width=None, max_height=None,
                      include_source=False) -> dict:
    ...
    return self.request("video.composite.capture", params)
```

`_NATIVE_ERROR_MAP` 新增：`CROP_OUT_OF_BOUNDS`、`COMPOSITE_UNSUPPORTED_BACKEND`、`COMPOSITE_UNSUPPORTED_FORMAT`、`COMPOSITE_DEVICE_LOST`，各自對應新的 exception class。

### 7.2 `ai/server.py`

```python
@mcp.tool()
def capture_composite(format: str = "png", crop: str = "viewport",
                      game_rect: dict = None, rect: dict = None,
                      max_width: int = None, max_height: int = None,
                      include_source: bool = False):
```

- `format="png"` 時回傳 `[metadata, Image(composite)]`；`include_source=true` 時回傳 `[metadata, Image(composite), Image(source)]`。
- Docstring 必須明確說明與 `capture_frame` 的差異：

| | `capture_frame` | `capture_composite` |
|---|---|---|
| 擷取層 | Scaler 之前的 guest 原生畫面 | Backend present 前的最終畫面 |
| 解析度 | Guest 解析度（mode 13h 為 640×400） | Back buffer 解析度（視窗或全螢幕） |
| 包含 shader、濾鏡、letterbox | 否 | 是 |
| 包含 Modern overlay | 否 | 是（M6 之後） |
| 適合用途 | 比對 DOS framebuffer、CRC、找像素 | 驗收玩家實際看到的畫面、overlay 位置、清晰度 |

### 7.3 `AGENT_GUIDE.md` / `AGENT_GUIDE.zh-TW.md`

新增一段「何時使用哪一個擷取工具」，內容即為上表，並加上規則：**判斷 HiRes 文字是否清晰、位置是否正確，一律使用 `capture_composite` 搭配 `game_rect` 裁切。**

## 8. 效能要求

| 情境 | 要求 |
|---|---|
| 沒有待處理請求 | 每次 present 只有一次 relaxed atomic load；frame time 與 baseline 無可量測差異 |
| 有請求 | D3D9 的 `GetRenderTargetData` 會讓 GPU 同步，只影響該次 present。記錄 1080p 下的讀回耗時 |
| PNG 編碼 | 在 socket thread 執行，不可以在 present thread 或 emulator thread 執行 |
| 記憶體 | System-memory surface 與 RGBA buffer 重複使用，不可以每次請求都重新配置 D3D 資源 |

## 9. 驗收測試

測試程式：`drive_c/` 新增 `COMPTEST.COM`（mode 13h）：
- 全畫面畫 1px 寬的不同顏色外框（用來偵測 viewport 邊界）
- 在已知的 game 座標畫幾個純色矩形標記，例如 `(40,30,16,8)`、`(200,150,32,16)`
- 按鍵後切換到另一組標記位置（測試靜止畫面與 frame 對應）

| # | 測試 | 通過條件 |
|---|---|---|
| T1 | PNG 有效性 | PNG signature 正確；Pillow 可解碼；尺寸等於 `width`×`height` |
| T2 | Backend 回報 | `backend` 與設定檔的 `output=` 一致（`default` 解析後為 `direct3d`） |
| T3 | Viewport 幾何 | `crop="full"` 擷取中偵測到的外框邊界 = `geometry.viewport` ±1px；在 3 種視窗大小（含非整數倍）與全螢幕下都成立 |
| T4 | `game_rect` 換算 | 以標記矩形的 game 座標裁切，結果內部 ≥ 95% 像素為標記色（邊緣容許濾鏡造成的混色） |
| T5 | 與 source 一致 | `include_source=true`、`output=direct3d`、nearest 濾鏡、整數倍縮放、無 shader：在 viewport 內每個 source pixel 對應區塊的中心取樣，與 source 像素**完全相同**；bilinear 設定下改用容差 ≤ 8/255 |
| T6 | Frame 對應 | 按鍵切換標記後立即擷取：`source_frame_match=true` 時，composite 與 source 的標記位置一致，沒有新舊 frame 混用 |
| T7 | 靜止畫面 | Guest 停在靜止畫面（仍在執行）時，擷取在 timeout 內成功 |
| T8 | 視窗被遮擋 | 另一個視窗蓋住 DOSBox-X 時，擷取結果不受影響 |
| T9 | 最小化與 breakpoint | 回傳 `EXECUTION_TIMEOUT`（依文件預期），且之後的擷取恢復正常 |
| T10 | Resize／全螢幕切換 | 切換後第一次擷取的尺寸正確；不 crash、不洩漏 D3D 資源 |
| T11 | Shader（如果你有使用） | 擷取結果包含 shader 效果（與 `capture_frame` 明顯不同） |
| T12 | 不支援的 backend | `output=ttf` 時回傳 `COMPOSITE_UNSUPPORTED_BACKEND`，不會回退成 source 畫面 |
| T13 | 穩定性 | 連續 50 次擷取：無 stall、無 crash；之後 `debug.status` 正常 |
| T14 | Payload | 1080p `rgba` 成功；1440p 以上 `rgba` 回傳 `FRAME_TOO_LARGE` 並附建議尺寸 |
| T15 | 零負擔 | 沒有請求時，以 COMPTEST 跑 60 秒，frame time 與 Phase 9A 之前的 build 無可量測差異 |

T3–T6 必須寫成 `tests/phase9a/` 下的 pytest（不要再只用一次性的 scratch script；Phase 7A 留下的待辦也在此一併處理）。

## 10. 實作步驟（交給 Codex，一次一步）

| Step | 內容 | 驗收 | STOP |
|---|---|---|---|
| C1 | Runtime 確認：`output=` 解析結果、D3D back buffer 格式、`MultiSampleType`、`D3D_THREAD` 是否生效；寫成報告 | 每項都有 log 證據（Observed） | ✅ |
| C2 | 新增 `present_hook.h/.cpp`、請求佇列、`render_seq` 計數器與 Arm 邏輯；**只接 surface backend** | T1、T3、T7（surface） | ✅ |
| C3 | Bridge method `video.composite.capture` + client + MCP tool + 錯誤碼 | T12、T14 | ✅ |
| C4 | D3D9 readback（worker thread）＋ seq 傳遞 ＋ force-present | T1–T10（direct3d） | ✅ |
| C5 | `game_rect`、`include_source` | T4、T5、T6 | ✅ |
| C6 | 穩定性、效能、shader | T11、T13、T15 | ✅ |
| C7 | pytest 套件、`AGENT_GUIDE` 雙語更新、`CHANGELOG` | 全部測試在 CI／本機通過 | ✅ |
| （P1）C8 | OpenGL backend，含 force-present 驗證 | T1–T10（openglnb） | ✅ |

每個 Step 的限制：
- 只在 `src/debug/debug_ai.*`、新增的 `present_hook.*`、`render.cpp` 的一個接點、各 backend 的 present 前一行，以及 `ai/` 下的檔案動工。
- 不可以修改 `render.forceUpdate`、不可以改變 present 順序、不可以在 present thread 做 PNG 編碼。
- 不可以改變既有 `capture_frame` 的行為與輸出（Phase 7A 的驗證項目必須全部維持通過）。

## 11. 未決事項

| # | 問題 | 何時解決 |
|---|---|---|
| U1 | 你實際使用的 `output=` 與是否啟用 D3D pixel shader | C1 |
| U2 | D3D back buffer 在你的機器上是否為 `X8R8G8B8`、是否有 multisample | C1 |
| U3 | 視窗最小化時 D3D9 是否仍會 present（決定 T9 的預期結果） | C4 |
| U4 | OpenGL 在靜止畫面時如何安全地 force 一次 swap | C8 |
| U5 | 高 DPI 下 back buffer 尺寸是否等於實體像素（影響 `scale` 數值的解讀） | C4 |

## 12. 實作紀錄（與設計的差異）

實作位置：`include/present_hook.h`、`src/gui/present_hook.cpp`（新增）、`src/debug/debug_ai.cpp`、`src/gui/render.cpp`、`src/output/direct3d/direct3d.{h,cpp}`、`src/output/output_surface.cpp`、`ai/dosbox_client.py`、`ai/server.py`、`tests/phase9a/`。

### 12.1 Force-present 改用「完整重繪」，不用 `GFX_EndUpdate(nullptr)`

§4.4 原本打算在 `render.cpp:546` 多呼叫一次 `GFX_EndUpdate(nullptr)`。實作前再查 source 發現這條路走不到 D3D：`GFX_EndUpdate()`（`sdlmain.cpp`）在 `!sdl.updating` 時會直接 return，除非 D3D pixel shader 要求 force update（`d3d->getForceUpdate()`）。畫面沒有變化時根本沒有呼叫 `GFX_StartUpdate()`，所以 `sdl.updating` 是 false，F8 那段註解（「works only with Direct3D」）只在有 shader 的情況下成立。

改為：有**尚未 Arm** 的請求時，`RENDER_StartUpdate()` 走與 cache clear 相同的完整重繪路徑（`render.scale.clearCache || PRESENT_Composite_WantsFullFrame()`）。這樣下一個 frame 一定會 `GFX_StartUpdate()` → 所有行都送進 backend → present。好處：與 backend 無關（surface、D3D、未來的 OpenGL 都適用），也不需要碰 `render.forceUpdate` 或 `render.scale.clearCache` 本身。代價：每個請求多一次完整重繪，只在有請求時發生。

因此 `render.cpp` 有三個接點而不是一個：`RENDER_EndUpdate()` 開頭遞增 `render_seq`、`RENDER_StartUpdate()` 的 force 條件、`RENDER_EndUpdate()` 裡（Phase 7A 擷取點旁）的 Arm。

### 12.2 只在「這個 frame 會被 present」時 Arm

Arm 條件是 `!abort && render.scale.outWrite != nullptr`，也就是這個 frame 一定會以 `GFX_EndUpdate(changedLines)` 送進 backend。配合 12.1，請求送出後的下一個 frame 就會 Arm 並 present，因此實測 `presented_render_seq == target_render_seq`（`source_frame_match=true`）在靜止畫面與按鍵切換後都成立。

### 12.3 Surface 的讀回點

`OUTPUT_SURFACE_EndUpdate()` 有多個分支與提早 return。實作把原函式改名為 `OUTPUT_SURFACE_EndUpdate_Present()`，外層包一個只呼叫它、再呼叫 hook 的 `OUTPUT_SURFACE_EndUpdate()`。`sdl.surface` 在 present 之後內容不變（與 D3D 的 `DISCARD` 不同），所以在 present 之後讀回得到的就是剛顯示的畫面，而且一個接點就涵蓋所有分支。

### 12.4 `guest_native` 的推導

§6.1 寫的是「`render.src` 扣除 `dblw`／`dblh`」。實際上 mode 13h 送進 renderer 的是 320×400（CRTC 的 scanline doubling 被保留成真實的行），`RENDER_SetSize()` 再用 `dblw` 放大成 640×400。所以 `render.src.width` 本身就是原生寬度；高度則在 EGA/VGA 圖形模式、`vga.draw.doublescan_effect` 為真時，除以 `vga.draw.address_line_total`（`ResolveGuestNativeSize()`）。實測 mode 13h 回報 320×200。

### 12.5 修正 Phase 7A 的 DBLW 解包錯誤（會改變 `capture_frame` 輸出）

T5 抓到一個 Phase 7A 就存在的錯誤：`UnpackFrameToRGBA8888()` 在 DBLW 時把第 x 個 source 像素寫到輸出的第 x 格（而不是 2x），結果 `capture_frame` 在 mode 13h 回傳的影像是「整個畫面擠在左半邊、右半邊是條紋」。尺寸（640×400）一直是對的，所以之前沒被發現。已修正；這違反了 §10「不可以改變 `capture_frame` 的輸出」的字面要求，但改變的只有錯誤的像素內容，寬高與欄位都不變。`include_source` 與 `capture_frame` 共用同一個解包函式，`tests/phase9a` 有一個測試確認兩者在靜止畫面上逐位元組相同。

### 12.6 C1 事實

| 項目 | 結果 | 依據 |
|---|---|---|
| `output=default` 解析結果 | `direct3d` | Observed（runtime：未指定 `output` 時回傳 `backend="direct3d"`） |
| `MultiSampleType` | `D3DMULTISAMPLE_NONE` | Observed（source）：`InitializeDX()` 以 `ZeroMemory` 清空 `d3dpp` 後從未設定此欄位；讀回程式仍會檢查，非 NONE 時回傳 `COMPOSITE_UNSUPPORTED_FORMAT` |
| Back buffer 格式 | 32-bit（B,G,R,X 排列） | Observed（runtime）：32-bit 路徑轉出的顏色與 source 一致 |
| `D3D_THREAD` | 生效（`direct3d.h:28` 為 1），讀回在 D3D worker thread 執行 | Observed（source） |
| D3D 取樣濾鏡 | 固定為 `D3DTEXF_LINEAR`（`SetupSceneScaled()`），沒有 nearest 選項 | Observed（source）。因此 T5 的「完全相同」條件無法在 D3D 上成立，測試改為「3×3 鄰域同色的 source 像素，在 composite 區塊中心的顏色容差 ≤ 8/255」 |

### 12.7 `output=ttf` 的判定

TTF 輸出不會改變 `sdl.desktop.type`（仍是切換前的 backend，Windows 上為 `direct3d`），而是在 `GFX_EndUpdate()` 裡因 `ttf.inUse` 提前 return 交給文字 renderer。所以 backend 判定必須另外看 `ttf.inUse`，否則請求會等到逾時而不是回傳 `COMPOSITE_UNSUPPORTED_BACKEND`。另外，TTF 只處理文字模式：在圖形模式（例如 mode 13h）下 `ttf.inUse` 為 false，DOSBox-X 實際是透過 `direct3d` present，此時擷取成功、回報 `backend="direct3d"` 是正確行為。T12 因此改為「圖形模式下正常擷取、回到文字模式後回傳不支援」。

### 12.8 自動化與手動驗收

自動化（`tests/phase9a/`，會自行啟動 DOSBox-X 並執行 `COMPTEST.COM`，由 `tests/phase9a/make_comptest.py` 產生）：T1、T2、T3、T4、T5、T6、T7、T9（breakpoint 部分）、T12、T13、T14，另加參數驗證與 `capture_frame` 回歸測試。T3 的全螢幕案例需要 `PHASE9A_FULLSCREEN=1`。

2026-09-30 本機結果：`python -m pytest tests/phase9a` → 26 passed、1 skipped（全螢幕）。T3–T5 涵蓋 `direct3d`（原始、1280×800、1000×700）與 `surface`（原始、1000×700）。實測觀察：

- 本機 `windowresolution=original` 時 back buffer 為 669×418（非整數倍 2.09），正好提供非整數倍的案例。
- `surface` 會忽略 `windowresolution`，viewport 為 640×400 置中於 669×418（有黑邊），T3 的黑邊／viewport 偵測也涵蓋到了。
- T4 依「內部」判定：排除裁切邊緣 2px 的混色帶後，標記色 ≥ 95%。
- T6：按鍵後**立即**擷取可能抓到 guest 重繪到一半的 frame，但 composite 與 source 每次都逐標記一致（沒有新舊 frame 混用）；等 0.3 秒後兩組標記都有觀察到。
- D3D 擷取（669×418 全畫面，含 base64 傳輸）約 50ms。

仍需手動：T8（視窗被遮擋）、T9 的最小化部分（U3）、T10（執行中 resize／切全螢幕）、T11（pixel shader）、T15（零負擔量測）、U5（高 DPI）。
