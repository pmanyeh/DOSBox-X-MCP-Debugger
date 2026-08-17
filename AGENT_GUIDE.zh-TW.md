# AI Agent 使用說明

*[English](AGENT_GUIDE.md) | [繁體中文](AGENT_GUIDE.zh-TW.md)*

本文件是給 **AI agent**（或負責設定 agent 的人）使用的參考手冊：說明要安裝
什麼、如何啟動整套系統、agent 可以呼叫的每一個工具、每個工具會回傳什麼，
以及需要處理的錯誤代碼——目標是讓 agent 真正能連線並操作一個正在執行中的
DOSBox-X 工作階段。

想瞭解本專案的緣起、目前狀態與設計理念，請見 [`README.md`](README.zh-TW.md)
與 [`docs/dosbox-ai-bridge.md`](docs/dosbox-ai-bridge.md)。本文件只涵蓋
「**怎麼用**」。

## 整體架構

```mermaid
flowchart LR
    A["AI agent"] -->|MCP over stdio| B["ai/server.py"]
    B -->|Python 呼叫| C["DOSBoxClient"]
    C -->|TCP，127.0.0.1:9876，\n換行分隔的 JSON| D["原生 AI 橋接層\n(dosbox-src/src/debug/debug_ai.cpp)"]
    D --> E["真實、正在執行中的\nDOSBox-X 除錯器與客體 CPU"]
```

- agent 透過 **MCP**（Model Context Protocol）以 stdio 的方式與
  `ai/server.py` 溝通——這是您的 MCP host（宿主程式）會啟動的行程。
- `ai/server.py` 只是一層薄薄的包裝：每一次工具呼叫，最終都會轉成一次對
  `DOSBoxClient`（`ai/dosbox_client.py`）的呼叫，而它透過一個簡單的、以換行
  分隔的 JSON-RPC 協定，經由一般的 TCP socket 溝通。
- 這個 socket 就是**原生 AI 橋接層**，直接編譯進 `dosbox-x.exe` 內
  （`dosbox-src/src/debug/debug_ai.cpp`）。它只綁定在 `127.0.0.1:9876`
  （僅限本機迴路，永遠無法從機器外部連線），而且操作的是與 DOSBox-X 除錯器
  GUI 本身完全相同的除錯器狀態與中斷點機制。整條路徑上沒有第二套 CPU
  模擬器、沒有 GUI 自動化，也沒有任何虛構出來的狀態。

agent 看到的一切都是真的：真實的暫存器、真實的記憶體、真實的中斷點、真實
的執行控制，以及透過 DOSBox-X 自己的輸入處理程式碼所送出的真實鍵盤／滑鼠
輸入。

## 所需環境

| 需求 | 說明 |
|---|---|
| Windows | 原生橋接層的 socket 程式碼雖有 POSIX 分支，但本專案只建置、測試並記載了 Windows（Visual Studio）版本。 |
| Visual Studio 2019 以上，含 C++ 桌面開發工作負載 | 只需要一次，用來從 `dosbox-src` 子模組建置出 `dosbox-x.exe`。執行期不需要它。 |
| Python 3.10 以上（已用 3.12 測試過） | 用來執行 `ai/server.py` 及 `ai/` 底下其餘程式。 |
| 一個支援 MCP 的 agent host | 任何能啟動 stdio 的 MCP 伺服器並呼叫其工具的程式（Claude Code、Claude Desktop，或其他 MCP 用戶端）皆可。 |

**不需要** Node/npm——這兩者只出現在本專案最早期的建置檢查腳本
（`ai/TASK.md`）中，用於初次設定時以 MCP Inspector 做人工檢查，與一般
使用無關。

## 安裝步驟

### 1. Clone（含子模組）

```
git clone --recurse-submodules https://github.com/pmanyeh/DOSBox-X-MCP-Debugger.git
```

Windows 上的長路徑注意事項，以及 `dosbox-src` 子模組應對齊的確切 commit，
請見 `README.md`「Getting started」章節。

### 2. 建立 Python 環境

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

這會安裝鎖定版本的 `mcp==2.0.0` SDK 以及 `pytest`。

### 3. 建置原生橋接層

用 Visual Studio 開啟 `dosbox-src\vs\dosbox-x.sln`，建置 `Release`（x64）
組態；或者從命令列：

```
cd dosbox-src\vs
msbuild dosbox-x.vcxproj /p:Configuration=Release /p:Platform=x64 /m
```

（若預設的工具集無法解析，請把 `/p:PlatformToolset=...` 改成您安裝的
Visual Studio 版本對應的工具集。）本專案只更動了原始碼，沒有更動建置系統
本身——`dosbox-src` 的建置方式與上游 DOSBox-X 完全相同。這個 fork 的
`dosbox-src/vs/config.h` 預設就已經同時啟用 `C_DEBUG` 與
`C_HEAVY_DEBUG`，所以一般的建置流程就已經包含 AI 橋接層與記憶體監看點
工具所需的一切，不需要額外旗標。

建置完成後會產生 `dosbox-src\bin\x64\Release\dosbox-x.exe`。

### 4. 啟動已載入 AI 橋接層的 DOSBox-X

在專案根目錄下執行：

```
dosbox-src\bin\x64\Release\dosbox-x.exe -defaultdir -break-start drive_c\YOURPROGRAM.EXE
```

- `-break-start <程式>` 會執行該程式，並讓除錯器立刻停在其進入點——這是
  除錯工作階段最常見的起始狀態。若要附掛到一個已經以一般方式啟動的程式，
  可省略這個參數，改在執行中呼叫 `pause_execution()`。
- `-defaultdir` 可以跳過「選擇工作目錄」的資料夾選取對話框——一個從未
  執行過的 `dosbox-x.exe` 路徑，第一次啟動時會跳出這個對話框，並且會卡住
  啟動流程（AI 橋接層的 socket 也還沒開），直到有人點掉它為止。
- 一旦程式啟動，原生 AI 橋接層就會自動在 `127.0.0.1:9876` 上監聽，不需要
  額外的步驟去「啟動」橋接層——它會隨著除錯器一起啟動
  （`DEBUG_AI_Init()`，由 `DEBUG_Init()` 呼叫）。

**如果是 agent 自己啟動 `dosbox-x.exe`（而不是人類雙擊執行檔，或從一般
終端機啟動），必須讓這個行程繼承一個真正的 Win32 console——不能在建立
行程時就把 stdout／stderr 重新導向或接管到檔案。**互動式除錯器主控台
（跟 AI 橋接層「僅限停止時」的方法共用同一條程式路徑——`pause_execution`、
`cpu.get`、`read_memory` 等等，全都需要跟人類按 Ctrl+Pause 時完全相同的
`DEBUG_Loop()`／主控台機制）會在除錯器第一次真正停止時，開啟自己的
console 視窗。如果這個行程自己的 std handle 在啟動時就被重新導向／
接管，這個主控台初始化過程可能會直接讓整個 `dosbox-x.exe` 行程當掉，
連帶讓 AI 橋接層一起掛掉——已確認會在「輸出被某個工具攔截、重新導向的
shell 呼叫」下發生，也確認在「行程直接繼承啟動者自己真正的 console」時
不會發生。實務上：啟動 `dosbox-x.exe` 這個動作本身，請避免用
`> file 2>&1` 這類重新導向，或自動化工具自己的輸出攔截包裝；若需要保留
日誌，請改在 `dosbox-x.conf` 的 `[log]` 區段設定 `logfile`（直接從行程
內部寫入真正的檔案，完全不會碰到 `STD_OUTPUT_HANDLE`），而不是在作業
系統層級重新導向這個行程自己的 stdout。不需要除錯器處於停止狀態的方法
（`capture_frame`、`get_mouse_capture`、執行中的鍵盤／滑鼠輸入等）則完全
不受影響。

### 5. 讓您的 MCP host 指向 `ai/server.py`

MCP 伺服器設定範例（請自行調整成您實際 clone 的路徑）：

```json
{
  "mcpServers": {
    "dosbox-x-debugger": {
      "command": "C:\\path\\to\\DOSBox-X-AI\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\DOSBox-X-AI\\ai\\server.py"]
    }
  }
}
```

`ai/server.py` 是不受限、通用的工具介面（共 31 個工具，詳見下方），也是
一般 agent 使用時應該連線的對象。另外還有兩個 MCP 進入點，用途較為特定、
較窄，**多數 agent 不應該**連線到它們：

- `ai/server_phase5a.py`——受限的唯讀／執行控制子集，供本專案自己的
  「工具感知」測試場景使用。
- `ai/server_phase5c.py`——同樣的 12 個工具子集，但包了一層有預算、有截止
  時間、會記錄證據的受限研究框架（`--total-budget`、`--exec-budget`、
  `--deadline-seconds`、`--allowed-tools`、`--evidence-log`），用於本專案
  自己的受控驗收測試。它完全沒有暴露 Phase 6A/6B 的工具。

### 6. 驗證

先呼叫 `ping` 工具——它應該回傳 `"DOSBox-X AI Debugger is alive."`，這個
呼叫完全不需要 DOSBox-X 正在執行（它不會碰橋接層）。接著，在按照第 4
步啟動 DOSBox-X 之後，呼叫 `get_debug_status`，確認回傳的是真正的
`stopped`／`location`／`registers` 快照，而不是 `DOSBOX_NOT_CONNECTED`
錯誤。

## 可用工具

共 31 個工具，依功能分類。「前置條件」是該呼叫要求的除錯器狀態；在錯誤的
狀態下呼叫，會得到明確的錯誤（見〈[錯誤代碼](#錯誤代碼)〉），而不是卡住或
悄悄地什麼都不做。

### 工作階段／中繼資訊

| 工具 | 參數 | 回傳 | 前置條件 |
|---|---|---|---|
| `ping` | 無 | `"DOSBox-X AI Debugger is alive."` | 無（不會碰 DOSBox-X） |
| `get_project_status` | 無 | `{"project", "phase", "dosbox_bridge", "debugger", "mcp"}` | 無 |

### 除錯器狀態（唯讀）

| 工具 | 參數 | 回傳 | 前置條件 |
|---|---|---|---|
| `get_debug_status` | 無 | 停止時：`{"stopped", "running", "location": {"cs","eip"}, "instruction": {"bytes","text"}, "registers", "segments", "flags"}`；執行中時：`{"stopped": false, "running": true}` | 無 |
| `get_cpu_state` | 無 | 暫存器／區段快照 | 無——**本身並不能**證明執行已停止；若需要這項證據請改用 `get_debug_status` |
| `get_current_instruction` | 無 | 目前 CS:EIP 處的指令 | 除錯器已停止 |

### 記憶體與反組譯

| 工具 | 參數 | 回傳 | 前置條件 |
|---|---|---|---|
| `read_memory` | `address: "SEG:OFF"`、`length: int` | `{"bytes": [...]}` | 除錯器已停止 |
| `disassemble` | `address: "SEG:OFF"`、`count: int` | 反組譯結果清單 | 除錯器已停止 |
| `write_memory` | `address: "SEG:OFF"`、`data: [0-255 的整數或 2 位十六進位字串, ...]` | 寫入確認 | 除錯器已停止 |

### 暫存器

| 工具 | 參數 | 回傳 | 前置條件 |
|---|---|---|---|
| `write_register` | `register: str`、`value: 十六進位字串` | 寫入確認 | 除錯器已停止；`register` 必須是 `eax/ebx/ecx/edx/esi/edi/ebp` 其中之一——EIP、區段暫存器、ESP、EFLAGS 一律會被拒絕（`REGISTER_NOT_WRITABLE`），以避免執行狀態失步 |

### 中斷點

| 工具 | 參數 | 回傳 | 前置條件 |
|---|---|---|---|
| `set_breakpoint` | `address: "SEG:OFF"` | 中斷點 id | 除錯器已停止；若該位址已有中斷點則回傳 `BREAKPOINT_ALREADY_EXISTS` |
| `set_real_memory_breakpoint` | `address: "SEG:OFF"` | 中斷點 id、`"type": "memory"` | 設定當下除錯器需已停止；之後（在 continue／step 時）該位元組的值被改變時才會觸發 |
| `set_protected_memory_breakpoint` | `address: "SELECTOR:OFFSET"` | 中斷點 id、`"type": "protected_memory"` | 同上，保護模式版本 |
| `delete_breakpoint` | `breakpoint_id: int` | 刪除確認 | id 必須存在（否則 `BREAKPOINT_NOT_FOUND`）；id 是 DOSBox-X 自己中斷點清單中的**位置**，新增／刪除中斷點時會位移——不確定時請重新呼叫 `list_breakpoints` |
| `list_breakpoints` | 無 | `{"id", "address", "type", "enabled"}` 的清單，`type` 為 `"code"`、`"memory"` 或 `"protected_memory"` | 無 |

這兩個記憶體監看點工具使用 DOSBox-X 自己的位元組變化監看機制（BPPM），
只有在 heavy-debug 建置下才可用（否則回傳 `INTERNAL_ERROR`）——這個
fork 的預設建置設定已經啟用它，見〈[安裝步驟](#安裝步驟)〉。

### 執行控制

| 工具 | 參數 | 回傳 | 前置條件 |
|---|---|---|---|
| `continue_execution` | 無 | `{"stopped": false, "running": true}` | 除錯器已停止；否則回傳 `ALREADY_RUNNING` |
| `pause_execution` | 無 | CPU 真正停止後拍下的真實 `debug.status` 快照 | 客體正在執行；否則回傳 `ALREADY_STOPPED`；若在時限內未完成則回傳 `EXECUTION_TIMEOUT` |
| `step_into` | 無 | 剛好執行一個指令之後的除錯狀態快照 | 除錯器已停止；否則回傳 `ALREADY_RUNNING` |
| `step_over` | 無 | 該指令執行完之後的除錯狀態快照（若是 CALL/INT/LOOP/REP，會先讓它完整跑完） | 除錯器已停止；否則回傳 `ALREADY_RUNNING`；若被跳過的呼叫未在時限內返回則回傳 `EXECUTION_TIMEOUT`（之後可用 `get_debug_status` 確認是否隨後已完成） |

### 鍵盤輸入

本節與下一節（滑鼠輸入）裡的每個工具──但不包含 `release_all_input`
以及下方「滑鼠捕獲狀態與絕對座標定位」的工具──都會在自己原本的回傳
欄位之外，額外附上 `"queued": true, "dispatched": true,
"dispatched_at_emulated_ms": int, "input_sequence": int,
"guest_observed": "not_supported"`。`input_sequence` 是這些工具共用的
單一遞增序號空間；之後可以拿它呼叫 `get_input_receipt` 回頭查這次
dispatch（見下方「輸入 dispatch receipt」）。

| 工具 | 參數 | 回傳 | 前置條件 |
|---|---|---|---|
| `key_down` | `key: str` | `{"pressed": true}` | **客體正在執行中**（不是停止狀態）；否則回傳 `DEBUGGER_STOPPED` |
| `key_up` | `key: str` | `{"pressed": false}` | 同上 |
| `key_tap` | `key: str` | `{"tapped": true}` | 同上——最常見的用法，例如 `key_tap("enter")` 用來推進對話 |

這三個工具都是透過與 DOSBox-X 自己的 SDL 鍵盤處理常式完全相同的內部路徑
（`KEYBOARD_AddKey()`）送出——絕對不是作業系統層級的按鍵注入、視窗焦點
操作，或 GUI 自動化。

`key` 必須是以下固定白名單中的一個（無法辨識的名稱會回傳
`INVALID_PARAMETER`，不會被亂猜）：

```
數字：       1 2 3 4 5 6 7 8 9 0
字母：       q w e r t y u i o p a s d f g h j k l z x c v b n m
功能鍵：     f1 f2 f3 f4 f5 f6 f7 f8 f9 f10 f11 f12
控制鍵：     esc tab backspace enter space
修飾鍵：     leftalt rightalt leftctrl rightctrl leftshift rightshift
             capslock scrolllock numlock
標點符號：   grave minus equals backslash leftbracket rightbracket
             semicolon quote period comma slash
導覽鍵區：   printscreen pause insert home pageup delete end pagedown
方向鍵：     left up down right
數字鍵盤：   kp1 kp2 kp3 kp4 kp5 kp6 kp7 kp8 kp9 kp0
             kpdivide kpmultiply kpminus kpplus kpenter kpperiod
```

這是標準美式 104 鍵配列。Windows 鍵、F13-F24，以及日文／韓文專用按鍵目前
尚未支援。自由輸入文字（`type_text`）這個版本也還沒有——原因請見
[`docs/phase6b-input-injection-design.md`](docs/phase6b-input-injection-design.md)。

**按下的按鍵會依 MCP 工作階段個別追蹤，若連線中斷**（agent 當掉、
工作階段逾時）**而還沒呼叫 `key_up`，會自動釋放**——按鍵絕不會因為 agent
消失而永遠卡在按下狀態。也可以主動呼叫 `release_all_input` 來提前釋放。

### 滑鼠輸入

| 工具 | 參數 | 回傳 | 前置條件 |
|---|---|---|---|
| `move_mouse_relative` | `dx: 數字`、`dy: 數字` | `{"moved": true}` | 客體正在執行中；否則回傳 `DEBUGGER_STOPPED` |
| `set_mouse_button` | `button: 0\|1\|2`、`pressed: bool` | `{"pressed": bool}` | 同上 |
| `click_mouse` | `button: 0\|1\|2` | `{"clicked": true}` | 同上 |
| `release_all_input` | 無 | `{"released": true}` | 釋放此工作階段目前按住的所有按鍵／滑鼠按鍵——只要客體正在執行，隨時都可以安全呼叫，即使目前沒有按住任何東西也一樣 |

`button` 為 `0`（左鍵）、`1`（右鍵）、`2`（中鍵）。全部都是透過
`Mouse_CursorMoved()`／`Mouse_ButtonPressed()`／`Mouse_ButtonReleased()`
送出——與 DOSBox-X 自己的 SDL 滑鼠處理常式呼叫的函式完全相同。

**已知限制**：`move_mouse_relative` 只有在 DOSBox-X 的滑鼠處於捕獲狀態
（`Ctrl+F10`）、且客體正在執行會讀取相對位移的驅動程式時才會生效——這個
呼叫本身不會去切換滑鼠捕獲狀態。按鍵按下／點擊則沒有這個限制。

### 畫面截取

| 工具 | 參數 | 回傳 | 前置條件 |
|---|---|---|---|
| `capture_frame` | `format: "png"\|"rgba"`（預設 `"png"`）、`max_width: int`（選填）、`max_height: int`（選填） | `format="png"`：可直接檢視的圖片，外加中繼資料區塊（`frame_id`、`width`、`height`、`captured_at_emulated_ms`）；`format="rgba"`：`{"frame_id", "width", "height", "pixel_format": "rgba8888", "rgba_base64", ...}` | 停止或執行中皆可呼叫，但請見下方說明 |

擷取的是客體自己算出來的畫面本身——絕對不是 DOSBox-X 視窗、主機桌面，或
任何其他主機視窗——透過的是與 DOSBox-X 自己的截圖／AVI 錄影功能完全相同
的內部掛鉤點。整個過程絕不會寫入主機磁碟。想直接看畫面時用預設的
`"png"`；需要精確的像素值（例如比對某個已知座標的顏色）而不是用眼睛看時
用 `"rgba"`。

`max_width`／`max_height` 會在原生畫面超過這個尺寸時做等比例的最近鄰縮小；
兩者都不填就維持原生解析度。若編碼後的畫面仍超過橋接層的大小上限，呼叫會
失敗並回傳 `FRAME_TOO_LARGE`，錯誤訊息裡會附上建議縮小後的
`max_width`／`max_height`——絕不會偷偷把畫面截斷。

**完全停止的客體不會產生新的畫面**（VGA 畫面更新的時機是由只有在客體真正
執行時才會觸發的硬體事件驅動）——在除錯器停止時呼叫 `capture_frame`，
通常會逾時（`EXECUTION_TIMEOUT`）而不是立刻回傳結果。要穩定擷取，請先呼叫
`continue_execution()`。

### 滑鼠捕獲狀態與絕對座標定位

| 工具 | 參數 | 回傳 | 前置條件 |
|---|---|---|---|
| `get_mouse_capture` | 無 | `{"captured", "autolock", "mode": "absolute"\|"relative"\|"unavailable", "guest_width", "guest_height", "last_guest_x", "last_guest_y"}` | 停止或執行中皆可呼叫 |
| `set_mouse_capture` | `captured: bool` | 與 `get_mouse_capture` 相同結構 | 停止或執行中皆可呼叫；不支援時回傳 `CAPTURE_UNAVAILABLE` |
| `move_mouse_absolute` | `x: 數字`、`y: 數字`、`coordinate_space: "guest_pixels"\|"normalized"`（預設 `"guest_pixels"`）、`clamp: bool`（預設 `false`） | `{"queued", "dispatched", "guest_x", "guest_y", "coordinate_space": "guest_pixels", "clamped", "input_sequence"}` | 客體正在執行中；否則回傳 `DEBUGGER_STOPPED` |
| `click_at` | 同 `move_mouse_absolute`，外加 `button: 0\|1\|2`（預設 `0`） | 同 `move_mouse_absolute`，外加 `"clicked": true` | 同上 |

`set_mouse_capture` 的效果跟使用者按下 `Ctrl+F10` 完全相同——絕不會移動
主機游標、改變視窗焦點，或影響任何其他程式。`move_mouse_absolute`／
`click_at` 走的是 DOSBox-X 自己既有的無縫／整合滑鼠定位內部路徑——跟
`move_mouse_relative` 不同，這兩個呼叫都不需要滑鼠處於捕獲狀態。

`get_mouse_capture` 回傳的 `guest_width`／`guest_height` 一定跟
`capture_frame` 回報的當前畫面寬高一致（兩者都源自同一份 DOSBox-X
render 狀態），所以可以直接把 `capture_frame` 截圖裡挑到的像素座標，原封
不動地傳給 `click_at` 的 `"guest_pixels"` 座標空間——也就是「看畫面、點
座標」這個自然的流程。`"normalized"` 座標空間是 `[0.0, 1.0] x [0.0,
1.0]`，原點在左上角。超出範圍的座標若 `clamp=false` 會回傳
`INVALID_PARAMETER`；`clamp=true` 則會夾到合法範圍內。

**已知限制**：只有在 `get_mouse_capture` 的 `"mode"` 是 `"absolute"` 時，
絕對座標定位才可用——例如已啟動的客體作業系統，或沒有 virtual-8086 的
保護模式，會回報 `"relative"`，此時 `move_mouse_absolute`／`click_at`
會回傳 `ABSOLUTE_MOUSE_UNAVAILABLE`。`"last_guest_x"`／`"last_guest_y"`
是橋接層最後一次成功送達的座標——不是「客體程式真的讀到了」的保證（跟本
指南其他地方 `guest_observed` 類的警語一致）。

### 輸入 dispatch receipt

| 工具 | 參數 | 回傳 | 前置條件 |
|---|---|---|---|
| `get_input_receipt` | `input_sequence: int` | `{"queued", "dispatched", "dispatched_at_emulated_ms", "input_sequence", "guest_observed": "not_supported", "device": "keyboard"\|"mouse", "guest_observation": {"kind": null, "observed_at_emulated_ms": null}}` | 停止或執行中皆可呼叫；若該序號目前沒保留，回傳 `INPUT_RECEIPT_EXPIRED` |

用先前呼叫回傳的 `input_sequence`，回頭查一次鍵盤／滑鼠 dispatch——適合
在事後確認某次按鍵或點擊真的送到了
`KEYBOARD_AddKey()`／`Mouse_CursorMoved()`／`Mouse_ButtonPressed()`／
`Mouse_ButtonReleased()`，而不只是「RPC 呼叫本身成功回傳」。橋接層至少
會保留最近 4096 筆 dispatch 或最近 10 分鐘的資料，以先達到的門檻為準；
`INPUT_RECEIPT_EXPIRED` 不會區分「已被淘汰」跟「根本沒發過這個序號」。

本實作中 `"guest_observed"` 與 `"guest_observation"` 永遠是
`"not_supported"`／`null`——確認 DOS／BIOS 端的輸入狀態真的改變了（而不
只是橋接層送出去了），是留給未來 phase 的保留欄位，本指南不應該被理解
成這件事已經做到了。要驗證某次 dispatch 真的影響了客體，請改用
`capture_frame` 或記憶體監看點搭配確認。

## 錯誤代碼

每一次失敗都會以結構化的 `{"code", "message"}` 錯誤回傳（絕不是原始例外
或悄悄地什麼都不做）。以下是 agent 應該特別辨識、分別處理的代碼：

| 代碼 | 意義 | 建議處理方式 |
|---|---|---|
| `DEBUGGER_NOT_STOPPED` | 在執行中呼叫了「僅限停止時」的工具，且除錯器來不及即時停下 | 先呼叫 `pause_execution`，或先檢查 `get_debug_status` |
| `DEBUGGER_STOPPED` | 在停止狀態呼叫了「僅限執行中」的工具（輸入注入） | 先呼叫 `continue_execution` |
| `ALREADY_RUNNING` | 在已經執行中時呼叫 `continue_execution`／`step_into`／`step_over` | 先檢查 `get_debug_status` |
| `ALREADY_STOPPED` | 在已經停止時呼叫 `pause_execution` | 先檢查 `get_debug_status` |
| `EXECUTION_TIMEOUT` | `pause_execution`／`step_over` 未在時限內完成 | 呼叫 `get_debug_status`——它可能隨後已經完成 |
| `MEMORY_ERROR` | 要求的客體記憶體未對應／無法存取 | 不要用同樣的位址重試 |
| `REGISTER_NOT_WRITABLE` | 該暫存器不在可寫入白名單中 | 不要重試 |
| `BREAKPOINT_NOT_FOUND` | 該中斷點 id 目前不存在 | 呼叫 `list_breakpoints` 取得目前的 id |
| `BREAKPOINT_ALREADY_EXISTS` | 該位址已經有中斷點 | 直接使用既有的，或先 `delete_breakpoint` |
| `INVALID_PARAMETER` | 參數格式錯誤／超出範圍／無法辨識（例如未知的按鍵名稱、錯誤的滑鼠按鍵編號） | 修正參數後再試，不要原樣重試 |
| `INVALID_ADDRESS` | `"SEG:OFF"`／`"SELECTOR:OFFSET"` 字串格式錯誤 | 修正位址格式 |
| `INTERNAL_ERROR` | 原生橋接層本身的失敗，例如在非 heavy-debug 建置上設定記憶體監看點 | 除非改變建置／環境，否則無法重試 |
| `FRAME_TOO_LARGE` | `capture_frame` 編碼後的畫面超過橋接層的大小上限 | 用錯誤訊息裡的 `suggested_max_width`／`suggested_max_height` 重試 |
| `CAPTURE_UNAVAILABLE` | 呼叫 `set_mouse_capture` 時，目前的畫面輸出後端沒有可控制的捕獲狀態 | 目前本 fork 已知的建置都不會產生這個錯誤 |
| `ABSOLUTE_MOUSE_UNAVAILABLE` | 呼叫 `move_mouse_absolute`／`click_at` 時，絕對座標定位在客體目前的模式下無法使用 | 先檢查 `get_mouse_capture` 的 `"mode"` 欄位 |
| `INPUT_RECEIPT_EXPIRED` | `get_input_receipt` 的 `input_sequence` 目前沒有被保留 | 該序號無法重試——已被淘汰，或根本沒發過 |
| `DOSBOX_NOT_CONNECTED` | 用戶端層級：橋接層無法連線（DOSBox-X 未執行，或建置時未啟用 `C_DEBUG`） | 啟動或重新啟動 DOSBox-X |
| `DOSBOX_TIMEOUT` | 用戶端層級：橋接層未在時限內回應 | 通常是暫時性的；也可能代表 DOSBox-X 卡住了 |

## 範例工作流程

### 基本的設中斷點／檢視／單步流程

```
set_breakpoint("1000:0100")
continue_execution()
# ……中斷點觸發，除錯器真正停在該處……
get_debug_status()              # 確認已停止，查看暫存器／位置
read_memory("1000:0100", 16)
step_into()
get_cpu_state()
delete_breakpoint(0)
```

### 記憶體監看點＋輸入注入（這兩組工具正是為了這個場景而生——不需要
任何人手動點擊或打字，就能推進一個文字冒險／對話系統）

```
set_real_memory_breakpoint("0060:1234")   # 監看某個文字指標／緩衝區位元組
continue_execution()
key_tap("enter")                          # 推進客體的對話
# ……客體寫入被監看的位元組，執行在那裡停下……
get_debug_status()                        # 寫入發生後當下真實的 CS:EIP
read_memory("<cs>:<某個偏移>", 64)         # 檢視來源緩衝區
disassemble("<cs>:<eip>", 10)             # 向前／向後追蹤呼叫者
key_tap("enter")                          # 觸發下一步
```

## 限制與安全注意事項

- 橋接層只綁定在 `127.0.0.1`——絕對不要把 `9876` 這個 port 對外開放。
- 單一個 `DOSBoxClient` 連線並非執行緒安全，一次只能有一個請求在飛行中
  （對應原生橋接層「每條連線一次只處理一個請求」的設計）。一個 MCP
  工作階段本身自然就會滿足這個限制。
- 記憶體監看點（`set_real_memory_breakpoint`、
  `set_protected_memory_breakpoint`）需要 heavy-debug 建置——這個 fork
  預設就已經啟用，見〈[安裝步驟](#安裝步驟)〉。
- 目前版本的鍵盤輸入是固定的名稱白名單，不支援自由文字或原始 scan code。
- 滑鼠相對位移是否生效，取決於 DOSBox-X 的滑鼠捕獲狀態，而這組工具本身
  並不會去控制那個狀態。
- `capture_frame` 目前還不支援 `include_cursor: true`（會回傳
  `INVALID_PARAMETER`）——客體游標合成是一個明確記錄下來的待解問題，
  而不是被悄悄忽略。
- 這是一個工程預覽版本，還不是成品——依賴它做無人值守、高風險的用途之前，
  請先參閱 `README.md` 中誠實揭露的 Phase 5C 驗收結果。
