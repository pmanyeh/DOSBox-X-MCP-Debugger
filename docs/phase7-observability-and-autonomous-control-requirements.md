# Phase 7：客體畫面觀測、可靠輸入與 DOS I/O 追蹤需求

> 狀態：實作需求草案  
> 對象：DOSBox-X-AI 原生 bridge、Python client 與 MCP tool surface 的實作者  
> 前置：`docs/phase6b-input-injection-design.md`

## 1. 目的與問題陳述

Phase 6B 已能把鍵盤／相對滑鼠事件送進 DOSBox-X 的內部輸入路徑；它證明了
「bridge 已注入」這件事，卻不足以讓 agent 穩定地做真實遊戲的互動式除錯。

本 phase 要提供五項可觀測性／控制能力：

1. 不經主機桌面、直接取得客體 framebuffer 的截圖。
2. 查詢與切換 DOSBox-X 滑鼠 capture 狀態。
3. 使用客體座標做絕對滑鼠移動／點擊，並清楚回報輸入實際抵達的層級。
4. 在中斷點或記憶體監看點命中時，自動保留命中前後的指令與暫存器 trace。
5. 將 DOS 檔案 I/O 提升成可篩選、可讀取的事件紀錄。

這些能力的目標是讓 agent 可以回答「畫面現在是什麼」、「我點在何處」、「這個輸入
到哪一層為止」、「是哪個程式讀取哪個檔案並把資料寫到哪裡」，而非依賴主機視窗焦點、
手動截圖或猜測。

## 2. 共通契約與限制

- 所有新 RPC 一律仍只監聽 `127.0.0.1:9876`，不得增加遠端連線模式。
- 除明列的 `mouse.capture.set` 外，API 不得操作主機視窗焦點、移動主機游標、使用
  `SendKeys`、Win32 mouse injection 或任何桌面自動化。
- 客體執行中才可送輸入；若 debugger 已停止，輸入 API 必須回傳 `DEBUGGER_STOPPED`。
- 讀取 frame、capture 狀態、trace、I/O log 可以在停止或執行中呼叫；實作必須避免和
  emulator thread 的 framebuffer／事件資料競態。
- 所有有界緩衝區都必須有明確的最大筆數／最大 bytes、遺失計數與 reset 行為；不得因
  長時間遊戲而無限制成長。
- 除非另有明確工具，所有新 API 都是唯讀或暫時性控制；不得改寫客體記憶體、磁碟映像
  或遊戲存檔。
- Python wrapper、MCP schema、`AGENT_GUIDE.md`、`AGENT_GUIDE.zh-TW.md` 與測試必須
  在同一 PR 一起更新。

### 2.1 輸入「已接收」的精確定義

bridge 不能普遍證明某個任意 DOS 程式已處理一個按鍵或點擊；程式可能忽略輸入、在讀取前
切換狀態，或有自己的 input loop。因此 API 不可把「注入佇列已處理」誤稱為
`game_accepted=true`。

本規格使用下列三層、可驗證的結果：

| 層級 | 意義 | 可保證性 |
|---|---|---|
| `queued` | socket 請求已進入 bridge pending queue | bridge 可保證 |
| `dispatched` | emulator thread 已呼叫 DOSBox-X 的鍵盤／滑鼠入口 | bridge 可保證 |
| `guest_observed` | 可選的 DOS／BIOS 觀測器看到對應裝置狀態或事件 | 僅表示 DOS input 層看見，不表示遊戲邏輯已採用 |

高階 agent 若要驗證遊戲層結果，應搭配 screenshot、記憶體監看點或 trace，而不是把
`dispatched` 當作成功遊玩。

## 3. Epic A：直接客體 framebuffer 截圖

### 3.1 API

新增：

```text
video.frame.capture
params:
{
  "format": "png" | "rgba",
  "include_cursor": boolean,        // default false
  "max_width": integer | null,      // default null，維持原尺寸
  "max_height": integer | null      // default null，維持原尺寸
}

result (format=png):
{
  "frame_id": uint64,
  "width": uint32,
  "height": uint32,
  "pixel_format": "rgba8888",
  "cursor_included": boolean,
  "captured_at_emulated_ms": uint64,
  "png_base64": string
}

result (format=rgba):
{
  "frame_id": uint64,
  "width": uint32,
  "height": uint32,
  "pixel_format": "rgba8888",
  "cursor_included": boolean,
  "captured_at_emulated_ms": uint64,
  "rgba_base64": string
}
```

Python helper：`DOSBoxClient.capture_frame(...)`。MCP 應輸出原生 image content，避免
agent 先將 base64 寫成主機端暫存檔才能檢視。

### 3.2 行為要求

- 擷取來源必須是 DOSBox-X 最終客體畫面／render surface，而不是 Win32 視窗、SDL window
  或整個桌面；主機上其他視窗絕不可出現在結果中。
- 預設不含主機游標。`include_cursor=true` 時只能合成 DOSBox-X 已知的客體游標，不可讀取
  OS cursor。
- 寬高為實際 framebuffer 尺寸；若提供 `max_width`／`max_height`，維持長寬比並以高品質
  或明確文件化的 nearest-neighbor 規則縮放。
- `frame_id` 單調遞增。相同畫面可有不同 id；不要求影像去重。
- 不得停止 guest。擷取若需要跨執行緒複製，必須在 emulator thread 做一份有界 snapshot，
  再由 socket thread 壓縮／回傳。
- 預設 payload 上限 8 MiB；超限時回傳 `FRAME_TOO_LARGE`，並在錯誤資料中提供所需縮放
  建議，而不是截斷 PNG。

### 3.3 驗收

1. 在 320×200 VGA 與 640×480 SVGA 測試程式各擷取一張，PNG 可解碼、尺寸正確。
2. 將 DOSBox-X 視窗完全被其他主機視窗遮住後，截圖仍只含客體內容。
3. 連續 100 次 capture 不造成 guest 停止、記憶體線性成長或圖像撕裂。
4. `include_cursor=false/true` 的差異只限客體游標區域。

## 4. Epic B：capture 狀態與絕對滑鼠控制

### 4.1 API

```text
input.mouse.capture.get
params: {}
result:
{
  "captured": boolean,
  "autolock": boolean,
  "mode": "relative" | "absolute" | "unavailable",
  "guest_width": uint32 | null,
  "guest_height": uint32 | null,
  "last_guest_x": number | null,
  "last_guest_y": number | null
}

input.mouse.capture.set
params: { "captured": boolean }
result: same as capture.get

input.mouse.move_absolute
params:
{
  "x": number,
  "y": number,
  "coordinate_space": "guest_pixels" | "normalized",
  "clamp": boolean                 // default false
}
result:
{
  "queued": true,
  "dispatched": true,
  "guest_x": number,
  "guest_y": number,
  "coordinate_space": "guest_pixels",
  "clamped": boolean,
  "input_sequence": uint64
}

input.mouse.click_at
params:
{
  "x": number,
  "y": number,
  "button": 0 | 1 | 2,
  "coordinate_space": "guest_pixels" | "normalized",
  "clamp": boolean                 // default false
}
result: move_absolute result + { "clicked": true }
```

`normalized` 使用 `[0.0, 1.0] × [0.0, 1.0]`，左上為 `(0,0)`、右下為 `(1,1)`；
`guest_pixels` 使用 framebuffer 左上為原點。`click_at` 必須在同一 emulator-thread
dispatch 中完成 move、button down、button up，防止其他輸入插隊。

### 4.2 行為要求

- `capture.set` 只能控制 DOSBox-X 自己的 capture state，效果等同使用者在 DOSBox-X 中按
  `Ctrl+F10`；不得前景化視窗或改變其他程式的鼠標位置。
- 若目前 video backend／平台沒有可安全控制的 capture state，回傳 `CAPTURE_UNAVAILABLE`，
  不得假裝成功。
- `move_absolute` 僅在 DOS mouse integration 或已知可映射的模式下可用；不支援時回傳
  `ABSOLUTE_MOUSE_UNAVAILABLE`。既有 `move_relative` 行為不變。
- 若座標越界且 `clamp=false`，回傳 `INVALID_PARAMETER`；`clamp=true` 時夾到可用範圍並標示
  `clamped=true`。
- `last_guest_x/y` 代表 bridge 最後成功 dispatch 的客體座標，不得聲稱是遊戲程式讀取到的
  座標。
- 原有 `input.mouse.*` 回應應擴充 `input_sequence` 與 `dispatched`，保留既有欄位以維持相容。

### 4.3 驗收

1. `capture.set(true)`／`capture.set(false)` 後，`capture.get` 的狀態可立即且正確反映。
2. 在滑鼠測試客體內以九宮格點擊，`click_at` 每次都落入請求格，不受主機 DPI、視窗位置或
   視窗是否被遮擋影響。
3. 不支援 absolute mode 的建置會明確回傳 `ABSOLUTE_MOUSE_UNAVAILABLE`。
4. debugger stopped 時所有會送輸入的 API 回傳 `DEBUGGER_STOPPED`，無殘留按鍵／按鈕狀態。

## 5. Epic C：輸入 dispatch receipt 與客體觀測器

### 5.1 API

每個 `input.key.*` 與 `input.mouse.*` 成功回應均增加：

```json
{
  "input_sequence": 1234,
  "queued": true,
  "dispatched": true,
  "dispatched_at_emulated_ms": 98765,
  "guest_observed": "unknown" | "not_supported" | "observed"
}
```

新增查詢：

```text
input.receipt.get
params: { "input_sequence": uint64 }
result: 上述 receipt，另含
{
  "device": "keyboard" | "mouse",
  "guest_observation": {
    "kind": "bios_keyboard_buffer" | "mouse_driver" | null,
    "observed_at_emulated_ms": uint64 | null
  }
}
```

### 5.2 行為要求

- `dispatched=true` 只能在 emulator thread 已實際呼叫 `KEYBOARD_AddKey()`、
  `Mouse_CursorMoved()`、`Mouse_ButtonPressed()` 或 `Mouse_ButtonReleased()` 後回覆。
- `input.receipt.get` 至少保留最近 4096 筆或最近 10 分鐘的 receipt（先到者淘汰），並提供
  `INPUT_RECEIPT_EXPIRED`。
- `guest_observed` 為可選的 best-effort observability，不得延長輸入 RPC 等待時間超過
  100 ms。未支援時清楚回傳 `not_supported`。
- 初版可只實作 `queued` 與 `dispatched`；但 response schema 必須預留 `guest_observed`，避免
  之後破壞相容性。

### 5.3 驗收

1. 送入 `key_tap("enter")` 後，receipt 的 sequence 可查回，且 `dispatched=true`。
2. 對 stopped debugger 的失敗輸入不得產生成功 receipt。
3. 超出 ring buffer 的 id 回傳 `INPUT_RECEIPT_EXPIRED`，不回傳錯誤的另一筆資料。

## 6. Epic D：中斷點命中前後 trace

### 6.1 API

```text
trace.execution.configure
params:
{
  "enabled": boolean,
  "before_instructions": 0..4096,
  "after_instructions": 0..4096,
  "registers": ["ax", "bx", "cx", "dx", "si", "di", "bp", "sp", "cs", "ip", "flags"],
  "include_disassembly": boolean,   // default true
  "max_trace_bytes": 65536..4194304
}
result: { "enabled": bool, "configuration": {...} }

trace.execution.list
params: { "limit": 1..100, "after_trace_id": uint64 | null }
result: { "traces": [TraceSummary], "dropped_traces": uint64 }

trace.execution.get
params: { "trace_id": uint64 }
result:
{
  "trace_id": uint64,
  "trigger": {
    "kind": "code_breakpoint" | "memory_breakpoint" | "manual_pause",
    "breakpoint_id": uint32 | null,
    "location": "CS:IP",
    "emulated_ms": uint64
  },
  "before": [InstructionRecord],
  "after": [InstructionRecord],
  "complete_after": boolean,
  "dropped_instruction_count": uint64
}

InstructionRecord:
{
  "ordinal": int,
  "location": "CS:IP",
  "bytes_hex": string,
  "disassembly": string | null,
  "registers": { "ax": uint16, "...": uint16 }
}
```

### 6.2 行為要求

- `before` 使用執行中的 lock-free 或低開銷 ring buffer；被監看點觸發後，資料必須代表
  命中**前**已完成／正在執行的指令序列，並在文件中精確定義偏移語意。
- `after_instructions > 0` 時，命中後不得直接永久停住：bridge 應執行所要求的後續指令數、
  收集後停在可重現的位置。若又命中別的 breakpoint、程式結束或 timeout，
  `complete_after=false` 並附原因。
- 初版只需要 real-mode x86、單一 CPU、無條件 code/memory breakpoint；不要求 branch trace、
  source-level symbol 或全系統 instruction recording。
- 未啟用 trace 時，中斷點現有停住語意與效能不得改變。
- Trace 與 breakpoint 的對應必須以 id 留存，即使 agent 稍後刪除了 breakpoint。

### 6.3 驗收

1. 在已知 `mov [addr],ax` 的測試程式設定 write watchpoint，可取得至少 8 條 before，並正確
   顯示寫入指令與命中時暫存器。
2. 設 `after_instructions=3` 後，trace 含 3 條後續指令，CPU 最終停在第 3 條之後。
3. 把 `max_trace_bytes` 設為最小值時，不越界；回傳可辨識的 truncate／dropped metadata。
4. 未配置 trace 的基準跑速退化不得超過 2%；已啟用但未命中的常態跑速退化必須被量測並記錄。

## 7. Epic E：DOS 檔案 I/O 高階事件

### 7.1 範圍

初版追蹤 DOS `INT 21h` 的下列服務：

- `3Dh` Open
- `3Eh` Close
- `3Fh` Read
- `40h` Write（預設只記 metadata，不擷取內容）
- `42h` Lseek

可在後續版本擴充到 FCB、EXEC、DOS extender／protected-mode 介面；初版不得假裝涵蓋它們。

### 7.2 API

```text
dos.io.configure
params:
{
  "enabled": boolean,
  "operations": ["open", "close", "read", "write", "seek"],
  "path_globs": ["*.GFF", "SAVE-*"],
  "include_failed": boolean,          // default true
  "max_events": 100..100000
}
result: { "enabled": bool, "max_events": uint32 }

dos.io.list
params:
{
  "after_event_id": uint64 | null,
  "limit": 1..1000,
  "operation": "open" | "close" | "read" | "write" | "seek" | null,
  "path_glob": string | null
}
result: { "events": [DosIoEvent], "dropped_events": uint64 }

dos.io.clear
params: {}
result: { "cleared": true }

DosIoEvent:
{
  "event_id": uint64,
  "emulated_ms": uint64,
  "operation": "open" | "close" | "read" | "write" | "seek",
  "phase": "completed",
  "cs_ip": "CS:IP",
  "process": { "psp_segment": uint16 | null },
  "handle": uint16 | null,
  "path_dos": "C:\\GAME\\GPLDATA.GFF" | null,
  "path_host": string | null,
  "file_offset_before": uint64 | null,
  "requested_bytes": uint32 | null,
  "transferred_bytes": uint32 | null,
  "buffer": { "segment": uint16 | null, "offset": uint16 | null, "linear": uint32 | null },
  "result": { "carry": boolean, "ax": uint16, "dos_error": uint16 | null }
}
```

### 7.3 行為要求

- Event 必須在 INT 21h 呼叫完成後記錄，故 read 的 `transferred_bytes`、carry 與 AX 是真實
  結果，而非僅請求值。
- `file_offset_before` 是 read/write/seek 前可驗證的邏輯檔案位置；無法取得時為 `null`，不得
  猜測。
- `buffer` 對 read/write 必須記錄呼叫者所傳的 real-mode `DS:DX` 及線性位址；不要求複製緩衝
  內容。這使 agent 可將「讀入哪個檔案」與「後續哪個記憶體寫入」關聯。
- `path_host` 可能揭露主機檔案路徑，僅回傳已掛載 DOS drive 內的 canonical path；不得列舉
  或讀取掛載範圍外的檔案。
- glob 比對大小寫不敏感、使用 DOS path 分隔符；不符合 filter 的事件不得佔用 ring buffer。
- event ring buffer 預設 10,000 筆。溢位時淘汰最舊事件並遞增 `dropped_events`。

### 7.4 驗收

1. 對測試程式 Open → Lseek → Read 16 bytes → Close，順序得到四筆 completed event，路徑、
   handle、offset、requested/transferred bytes、DS:DX 與 AX 都正確。
2. 讀取不存在檔案時有 failed open event，carry=true 與 DOS error 正確。
3. `path_globs=["*.GFF"]` 時 SAVE 檔 I/O 不出現、不佔 ring buffer。
4. 將 Dark Sun 的 `SAVE05` 載入一次，可從 log 識別 `SAVE-37` 與相關 GFF 讀取，並能以
   `buffer.linear` 和既有記憶體監看點對照。

## 8. 實作順序（建議）

分成可獨立合併的四個 PR，避免把 renderer、input、debugger 與 DOS kernel hook 混在一個
大型變更中：

1. **PR A — Frame capture + capture status**：先完成 Epic A 與 `capture.get`；立即解除 agent
   必須依賴主機桌面截圖的問題。
2. **PR B — Absolute mouse + receipts**：完成 Epic B、C；包含自動化九宮格客體測試。
3. **PR C — Bounded execution trace**：完成 Epic D，維持未啟用時的既有 debugger 行為。
4. **PR D — DOS I/O event log**：完成 Epic E，先處理 real-mode INT 21h，再評估 extender。

每個 PR 都必須有：原生 bridge 單元／整合測試、Python client 測試、JSON schema 相容性測試、
至少一段 agent-guide 使用範例，以及在正常 DOSBox-X build 與 heavy-debug build 上的結果。

## 9. 非目標

- 不要求 OCR、影像辨識、遊戲物件辨識或自動路徑規劃。
- 不要求保證任意遊戲邏輯已消費輸入；只提供明確分層的 receipt。
- 不要求錄製完整影片或無限長 instruction trace。
- 不以此 phase 修改 DOSBox-X 的網路暴露、帳號／認證模型或遠端控制能力。
- 不以此 phase 實作任意文字輸入／IME／中文鍵盤注入。

## 10. 完成定義

Phase 7 可宣告完成的最低門檻是：agent 能在不讀取主機桌面、不要求人手移動滑鼠的情況下，
取得客體畫面、查詢／切換 capture、以客體座標點擊 UI、得知事件已由 emulator thread
dispatch；並能在一個指定記憶體監看點命中時讀到前後 trace，以及把一次 DOS read 關聯到
檔名、offset、bytes 與目標記憶體位址。所有契約需由自動化測試驗證。
