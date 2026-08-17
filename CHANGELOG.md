# Changelog

All notable changes to this project are documented here, grouped by
development phase (this project's own milestone convention -- see
`docs/`) rather than by date or semantic version, since no formal
release/version-number scheme exists yet. Each entry is presented in
English and Traditional Chinese together.

所有值得記錄的變更都整理在這裡，依照本專案自己的里程碑慣例（「Phase」，
詳見 `docs/`）分組，而不是依日期或語意化版本號——因為目前還沒有正式的
發行／版本號機制。每一條都會同時附上英文與繁體中文。

---

## Phase 7D — Bounded execution trace around a breakpoint hit (2026-08-17)

**English**

- Added `trace.execution.configure`/`.list`/`.get`. While enabled,
  every time the debugger genuinely stops (a code/memory breakpoint, a
  manual `pause_execution()`/Ctrl+Pause, or `-break-start`), a trace is
  captured automatically -- the instructions leading up to (and
  including) the stop, and, if `after_instructions>0`, that many
  instructions executed immediately afterward (the debugger's own
  visible stop position moves to reflect this).
- Reuses three existing mechanisms rather than inventing new ones:
  "before" comes from DOSBox-X's own existing heavy-debug instruction
  log (the same ring buffer its "LOG HEAVY" debugger-console command
  already writes into); "after" comes from the existing,
  already-verified `DEBUG_AI_DoStepInto()` (Phase 4D), called
  repeatedly from the exact context it already requires; trigger
  detection is a minimal, additive change to
  `CBreakpoint::CheckBreakpoint()`'s two existing `return true;` sites
  (records which breakpoint matched -- a resolved snapshot, never a raw
  pointer, since a "once" breakpoint is deleted in the very same call
  that matches it).
- The stop-transition hook wraps `DEBUG_AI_SetDebuggerActive()` itself
  (detecting the false->true transition) rather than touching
  `DEBUG_Enable_Handler()`/`DEBUG_Loop()` -- covers every entry point
  uniformly, since all of them already funnel through that one setter.
- Wired into `DOSBoxClient`/`ai/server.py` (bringing the tool count to
  34) and `AGENT_GUIDE.md`/`.zh-TW.md`. New error code
  `TRACE_NOT_FOUND`.
- Verified live end-to-end (raw protocol and the actual MCP tool
  functions) against a purpose-built test program: a real-mode memory
  watchpoint correctly triggered `trigger.kind="memory_breakpoint"`;
  `before` ended exactly at the trigger instruction; `after_instructions=4`
  produced exactly 4 entries, and a separate, independent
  `get_debug_status` call afterward confirmed the debugger's actual
  stop position matched the last `after` entry exactly -- direct proof
  the highest-risk part (calling `DEBUG_AI_DoStepInto()` from this new
  context) works correctly with no corruption or crash. Also verified
  a `manual_pause` trigger and `TRACE_NOT_FOUND`. Not independently
  exercised: `max_trace_bytes` truncation and a code-breakpoint trigger
  specifically (only memory breakpoints were exercised, though both
  share the same code path) -- tracked as follow-up.
- See `docs/phase7d-execution-trace-design.md` for the full design,
  source investigation, and verification notes.

This completes Epics A-D of the Phase 7 requirements draft's core
observability work; Epic E (DOS I/O event log) remains.

**繁體中文**

- 新增 `trace.execution.configure`／`.list`／`.get`。啟用期間，每次
  除錯器真正停止——不論是程式碼／記憶體中斷點、手動呼叫
  `pause_execution()`／Ctrl+Pause，還是 `-break-start`——都會自動擷取
  一筆 trace：包含停止前（含當下）的指令，以及，若
  `after_instructions>0`，停止後立刻執行的那幾個指令（除錯器本身可見
  的停止位置也會跟著移動以反映這點）。
- 重用了三個既有機制，而不是自創新的：「before」來自 DOSBox-X 自己既有
  的 heavy-debug 指令記錄（跟它「LOG HEAVY」除錯器主控台指令寫入的是
  同一個環狀緩衝區）；「after」來自既有、早就驗證過的
  `DEBUG_AI_DoStepInto()`（Phase 4D），從它本來就要求的那個情境重複
  呼叫；觸發偵測則是對 `CBreakpoint::CheckBreakpoint()` 兩個既有的
  `return true;` 位置做最小幅度的附加修改（記下是哪個中斷點命中——一份
  已解析的快照，絕不是原始指標，因為「一次性」中斷點會在命中的同一次
  呼叫裡就被刪除）。
- 停止轉換的掛鉤點包在 `DEBUG_AI_SetDebuggerActive()` 本身（偵測
  false→true 的轉換），而不是動 `DEBUG_Enable_Handler()`／
  `DEBUG_Loop()`——這樣可以統一涵蓋所有進入點，因為它們本來就全部會經過
  這同一個 setter。
- 已接上 `DOSBoxClient`／`ai/server.py`（工具數來到 34 個）與
  `AGENT_GUIDE.md`／`.zh-TW.md`。新增錯誤代碼 `TRACE_NOT_FOUND`。
- 已完整實機端對端驗證（原始協定與實際 MCP 工具函式）：針對一個特別
  寫的測試程式，real-mode 記憶體監看點正確觸發
  `trigger.kind="memory_breakpoint"`；`before` 精準結束在觸發指令上；
  `after_instructions=4` 剛好產生 4 筆記錄，事後另外獨立呼叫一次
  `get_debug_status`，確認除錯器實際的停止位置跟最後一筆 `after`
  完全吻合——直接證明了風險最高的部分（在這個新情境下呼叫
  `DEBUG_AI_DoStepInto()`）運作正確，沒有任何損壞或當機。也驗證了
  `manual_pause` 觸發與 `TRACE_NOT_FOUND`。這次沒有獨立驗證：
  `max_trace_bytes` 截斷，以及專門針對程式碼中斷點的觸發（這次只驗證了
  記憶體中斷點，但兩者走的是完全相同的程式路徑）——已記錄為後續追查
  項目。
- 完整設計、原始碼調查與驗證細節見
  `docs/phase7d-execution-trace-design.md`。

這次完成了 Phase 7 需求草案核心可觀測性工作的 Epic A-D；Epic
E（DOS I/O 事件記錄）還沒做。

---

## Bridge fix — debugger console crash on piped/redirected stdio (2026-08-17)

**English**

- Root-caused the `execution.pause`/`-break-start` reliability issue
  flagged in the Phase 7C entry above: `ResizeConsole()`
  (`src/debug/debug_win32.cpp`, called from `WIN32_Console()` the first
  time the debugger console opens -- Ctrl+Pause, `-break-start`,
  `execution.pause`, or the AI bridge's stopped-only methods all share
  this path) called `GetConsoleScreenBufferInfo()` without checking its
  return value, then used the resulting **entirely uninitialized**
  `CONSOLE_SCREEN_BUFFER_INFO` regardless. That call fails whenever the
  handle it's given isn't a genuine console screen buffer -- which
  happens whenever `dosbox-x.exe`'s own stdout/stderr were
  redirected/piped at process creation rather than inheriting a real
  console (confirmed via Windows Error Reporting crash dumps from an
  earlier session: exception `0xc0000409`,
  `STATUS_STACK_BUFFER_OVERRUN`, consistent with operating on garbage
  stack data). Fixed by bailing out early on failure -- verified this
  does not regress the working (real-console) case.
- This fix alone does not resolve every crash/silent-exit possible under
  piped stdio in this environment -- a second, deeper issue also exists
  in `DBGUI_StartUp()`'s own `AttachConsole()`/`AllocConsole()`/
  `freopen()`/`initscr()` sequence (`src/debug/debug_gui.cpp`), inside
  vendored PDCurses console initialization, not fixed this session.
- Practical takeaway, documented in `AGENT_GUIDE.md`/`.zh-TW.md`: an
  agent that launches `dosbox-x.exe` itself must give it a genuine
  inherited console, not stdout/stderr piped/redirected at process
  creation -- otherwise the debugger console (shared by every
  stopped-only AI bridge method) can crash the whole process. Confirmed
  live: a plain `Start-Process` (inheriting a real console) works;
  the identical launch with stdout/stderr redirected to a file, or
  piped through an automation tool's own output capture, crashes on the
  first genuine debugger stop either way.
- With a genuine console, the stopped-route gaps Phase 7B/7C's design
  docs had flagged as "not independently verified" were closed in this
  same session: `capture.get`/`.set` while genuinely stopped now
  confirmed to toggle/reflect correctly via the
  `g_requestQueue`/`DEBUG_AI_Poll()` route, and `move_absolute`/
  `click_at`/`key_tap`/`input.receipt.get` all behave exactly as
  designed while stopped -- see the updated Phase 7B/7C design docs.

**繁體中文**

- 追查出上面 Phase 7C 條目提到的 `execution.pause`／`-break-start`
  不穩定問題的根本原因：`ResizeConsole()`（`src/debug/debug_win32.cpp`，
  由 `WIN32_Console()` 呼叫，發生在除錯器主控台第一次開啟時——不論是
  Ctrl+Pause、`-break-start`、`execution.pause`，還是 AI 橋接層「僅限
  停止時」的方法，全都共用這條路徑）呼叫 `GetConsoleScreenBufferInfo()`
  時沒檢查回傳值，然後不管結果如何都直接使用那個**完全未初始化**的
  `CONSOLE_SCREEN_BUFFER_INFO`。這個呼叫在拿到的 handle 不是真正的
  console screen buffer 時就會失敗——而只要 `dosbox-x.exe` 自己的
  stdout／stderr 在建立行程時就被重新導向／接管（而不是繼承一個真正的
  console），就會發生這種情況（已透過上次 session 留下的 Windows Error
  Reporting 當機傾印檔確認：例外代碼 `0xc0000409`
  `STATUS_STACK_BUFFER_OVERRUN`，跟操作垃圾堆疊資料的現象吻合）。修法是
  失敗時提早返回——已驗證不會影響「有真正 console」這個正常運作的情境。
- 這個修正本身並不能解決這個環境下 piped stdio 可能造成的所有當機／
  無聲結束情況——`DBGUI_StartUp()` 自己的
  `AttachConsole()`／`AllocConsole()`／`freopen()`／`initscr()` 這串流程
  （`src/debug/debug_gui.cpp`）裡，也就是內附的 PDCurses console
  初始化程式碼中，還存在第二個更深層的問題，這次 session 沒有修。
- 已記錄在 `AGENT_GUIDE.md`／`.zh-TW.md` 的實務結論：如果是 agent 自己
  啟動 `dosbox-x.exe`，必須讓它繼承一個真正的 console，不能在建立行程時
  就把 stdout／stderr 重新導向或接管——否則除錯器主控台（被所有「僅限
  停止時」的 AI 橋接層方法共用）可能會讓整個行程當掉。已實機確認：單純
  用 `Start-Process`（繼承真正的 console）可以正常運作；完全相同的啟動
  方式只是把 stdout／stderr 重新導向到檔案，或被自動化工具自己的輸出
  攔截機制接管，兩種情況都會在除錯器第一次真正停止時當掉。
- 有了真正的 console 之後，Phase 7B／7C 設計文件裡標記為「未獨立驗證」
  的 stopped 路線缺口，在同一次 session 就補上了：`capture.get`／`.set`
  在除錯器真正停止時，已確認能透過 `g_requestQueue`／`DEBUG_AI_Poll()`
  這條路線正確切換與反映狀態；`move_absolute`／`click_at`／`key_tap`／
  `input.receipt.get` 在停止狀態下也都完全照設計運作——詳見更新後的
  Phase 7B／7C 設計文件。

---

## Phase 7C — Input dispatch receipts (2026-08-17)

**English**

- Every `input.key.*`/`input.mouse.*` dispatch (down/up/tap, relative
  move, button set/click, and Phase 7B's `move_absolute`/`click_at`)
  now returns `"queued": true, "dispatched": true,
  "dispatched_at_emulated_ms", "input_sequence", "guest_observed":
  "not_supported"` alongside its own result field -- one shared,
  monotonically increasing `input_sequence` space across all of them.
  `input.mouse.capture.get`/`.set` (Phase 7B) and `input.release_all`
  deliberately do NOT gain these fields -- neither dispatches guest
  input, so a "dispatch receipt" would misrepresent what happened; see
  the design doc's "What gets a receipt" section.
- New `input.receipt.get` looks up an earlier dispatch by
  `input_sequence`, whether the debugger is stopped or running,
  answered directly from the socket thread (a receipt is already-computed
  history, not live emulator state, so no request queue is involved).
  Backed by a mutex-guarded ring buffer retaining at least the most
  recent 4096 receipts or 10 minutes' worth, whichever bound an entry
  hits first; a stale/unknown sequence returns `INPUT_RECEIPT_EXPIRED`.
- `guest_observed`/`guest_observation` are always
  `"not_supported"`/`null` in this implementation -- real DOS/BIOS-side
  observation is reserved schema (per the requirements draft's explicit
  allowance), not implemented.
- Wired into `DOSBoxClient.get_input_receipt()`/`ai/server.py`'s
  `get_input_receipt` tool (bringing the tool count to 31),
  `AGENT_GUIDE.md`/`.zh-TW.md`. New error code `INPUT_RECEIPT_EXPIRED`.
- Verified live end-to-end: `key_tap`/`click_at`/`move_mouse_relative`
  each dispatched, and their receipts looked back up correctly by
  device and sequence; an unissued sequence correctly rejected; the
  scoping decision (capture.get/.set and release_all_input excluded)
  confirmed in the actual running responses, not just documented.
- See `docs/phase7c-input-dispatch-receipts-design.md` for the full
  design and verification notes.

**繁體中文**

- 每一次 `input.key.*`／`input.mouse.*` 的 dispatch（down／up／tap、
  相對移動、按鈕 set／click，以及 Phase 7B 的
  `move_absolute`／`click_at`）現在都會在自己原本的回傳欄位之外，附上
  `"queued": true, "dispatched": true, "dispatched_at_emulated_ms",
  "input_sequence", "guest_observed": "not_supported"`——這些工具共用
  同一個單一遞增的 `input_sequence` 序號空間。`input.mouse.capture.get`／
  `.set`（Phase 7B）與 `input.release_all` 刻意不會拿到這些欄位——兩者
  都沒有真的送出客體輸入，若附上「dispatch receipt」會誤導實際發生的
  事——詳見設計文件的「哪些呼叫會拿到 receipt」一節。
- 新增 `input.receipt.get`，可用 `input_sequence` 回頭查一次先前的
  dispatch，不論除錯器是停止還是執行中都能查，且直接在 socket thread
  上回答（receipt 是已經發生、算好的歷史紀錄，不是即時的 emulator
  狀態，不需要經過任何請求佇列）。背後是一個以 mutex 保護的環狀緩衝區，
  至少保留最近 4096 筆或最近 10 分鐘的 receipt，以先達到的門檻為準；
  過期或未知的序號會回傳 `INPUT_RECEIPT_EXPIRED`。
- 本實作中 `"guest_observed"`／`"guest_observation"` 永遠是
  `"not_supported"`／`null`——真正的 DOS／BIOS 端觀測是保留欄位（需求
  草案本來就明確允許 v1 只做到這裡），目前尚未實作。
- 已接上 `DOSBoxClient.get_input_receipt()`／`ai/server.py` 的
  `get_input_receipt` 工具（工具數來到 31 個）、
  `AGENT_GUIDE.md`／`.zh-TW.md`。新增錯誤代碼 `INPUT_RECEIPT_EXPIRED`。
- 已完整實機端對端驗證：`key_tap`／`click_at`／`move_mouse_relative`
  各自送出後，都能用序號正確查回對應的 device 與 receipt；未發過的
  序號正確被拒絕；範圍界定（`capture.get`／`.set` 與
  `release_all_input` 排除在外）在實際執行中的回應裡也確認成立，
  不只是寫在文件裡。
- 完整設計與驗證細節見
  `docs/phase7c-input-dispatch-receipts-design.md`。

---

## Phase 7B — Mouse capture status & absolute positioning (2026-08-17)

**English**

- Added `input.mouse.capture.get`/`.set`, `input.mouse.move_absolute`,
  and `input.mouse.click_at` to the native AI bridge. `capture.get`/
  `.set` work whether the debugger is stopped or running (unlike every
  other `input.*` method) via a new dual-route mechanism reusing the
  two existing request-drain hooks (`g_requestQueue`/`DEBUG_AI_Poll()`
  while stopped, `g_pendingInputs`/`DEBUG_AI_CheckPendingInput()` while
  running) rather than adding a third one.
- `move_absolute`/`click_at` reuse DOSBox-X's own existing
  seamless/integrated absolute-mouse-positioning code path
  (`Mouse_CursorMoved(..., emulate=false)`, `src/ints/mouse.cpp`) --
  not a bridge invention. New `Mouse_AbsolutePositioningAvailable()`
  (`mouse.h`/`mouse.cpp`) exposes exactly the condition that path
  already checks, so `ABSOLUTE_MOUSE_UNAVAILABLE` is never guessed at.
  `click_at` performs move + button-down + button-up in one
  emulator-thread dispatch, so nothing else can interleave.
- `"guest_pixels"` coordinates are computed from the SAME
  `render.src.width/height` formula Phase 7A's `video.frame.capture`
  already uses, so a pixel picked from a screenshot maps directly onto
  `click_at` -- verified live: all four exact frame corners
  (`(0,0)`/`(w-1,0)`/`(0,h-1)`/`(w-1,h-1)`) landed exactly on-pixel.
- Wired into `DOSBoxClient`/`ai/server.py` (bringing the tool count to
  30) and `AGENT_GUIDE.md`/`.zh-TW.md`. New error codes
  `CAPTURE_UNAVAILABLE`, `ABSOLUTE_MOUSE_UNAVAILABLE`.
- Verified live (running route only -- see design doc) via
  `DOSBoxClient`, the actual MCP tool functions, and raw protocol
  calls. The stopped route could not be independently exercised this
  session: this session's automated launch environment could not
  reliably reach a genuinely stopped debugger at all (`-break-start`
  left even the long-established `cpu.get` reporting
  `DEBUGGER_NOT_STOPPED`, and `execution.pause` crashed `dosbox-x.exe`
  outright on a completely fresh instance with no Phase 7B methods
  called) -- a pre-existing condition of this environment, not a
  regression from this work, and tracked as a follow-up rather than
  assumed fine.
- See `docs/phase7b-mouse-capture-and-absolute-input-design.md` for
  the full design, source investigation, and verification notes.

**繁體中文**

- 為原生 AI 橋接層新增 `input.mouse.capture.get`／`.set`、
  `input.mouse.move_absolute` 與 `input.mouse.click_at`。跟其他所有
  `input.*` 方法不同，`capture.get`／`.set` 不論除錯器是停止還是執行中
  都能運作——透過新的雙路由機制重用既有的兩個請求排空掛鉤點（停止時走
  `g_requestQueue`／`DEBUG_AI_Poll()`，執行中走 `g_pendingInputs`／
  `DEBUG_AI_CheckPendingInput()`），而不是再新增第三個掛鉤點。
- `move_absolute`／`click_at` 重用的是 DOSBox-X 自己既有的無縫／整合式
  絕對滑鼠定位程式路徑（`Mouse_CursorMoved(..., emulate=false)`，
  `src/ints/mouse.cpp`）——不是橋接層自創的機制。新增的
  `Mouse_AbsolutePositioningAvailable()`（`mouse.h`／`mouse.cpp`）
  暴露的正是該路徑本來就會檢查的條件，因此 `ABSOLUTE_MOUSE_UNAVAILABLE`
  絕不是用猜的。`click_at` 會在同一次 emulator-thread dispatch 中完成
  移動、按下、放開，中間不會有其他輸入插隊。
- `"guest_pixels"` 座標的計算方式，跟 Phase 7A `video.frame.capture`
  已經在用的 `render.src.width/height` 公式完全相同，因此從截圖挑到的
  像素座標可以直接對應到 `click_at`——已實機驗證：畫面四個精確角落
  （`(0,0)`／`(w-1,0)`／`(0,h-1)`／`(w-1,h-1)`）都精準落在像素上。
- 已接上 `DOSBoxClient`／`ai/server.py`（工具數來到 30 個）與
  `AGENT_GUIDE.md`／`.zh-TW.md`。新增錯誤代碼 `CAPTURE_UNAVAILABLE`、
  `ABSOLUTE_MOUSE_UNAVAILABLE`。
- 已實機驗證（僅限執行中路由——詳見設計文件）：透過 `DOSBoxClient`、
  實際的 MCP 工具函式，以及原始協定呼叫。這次 session 沒能獨立驗證
  「停止路由」：這次自動化啟動的環境完全無法穩定進入真正停止的除錯器
  狀態（`-break-start` 之後，連早就驗證過的既有方法 `cpu.get` 都回報
  `DEBUGGER_NOT_STOPPED`；而呼叫 `execution.pause` 甚至會讓
  `dosbox-x.exe` 直接當掉，在全新、沒呼叫過任何 Phase 7B 方法的實例上
  也一樣）——這是這個環境本來就有的既有問題，不是這次改動造成的
  回歸，已記錄為後續追查項目，而非假設沒事。
- 完整設計、原始碼調查與驗證細節見
  `docs/phase7b-mouse-capture-and-absolute-input-design.md`。

---

## Bridge fix — Windows double-bind on 127.0.0.1:9876 (2026-08-17)

**English**

- Fixed `DEBUG_AI_Init()` (`dosbox-src/src/debug/debug_ai.cpp`)
  unconditionally setting `SO_REUSEADDR` before `bind()`. On Windows
  (unlike POSIX) that lets a second DOSBox-X-AI instance successfully
  bind and listen on the same `127.0.0.1:9876` a first, still-running
  instance already owns, with no defined rule for which instance an
  agent's connection actually reaches -- silently contradicting the
  bridge's documented "failed bind disables the bridge safely"
  contract. Now guarded to POSIX only (`#if !defined(WIN32)`), mirroring
  a documented precedent already in this project's own vendored SDL_net
  (`vs/sdlnet/SDLnetTCP.c`, `vs/sdl2net/SDLnetTCP.c`) for the identical
  pitfall.
- Verified live with two concurrent `dosbox-x.exe` instances: the
  second's `bind()` now fails and logs `bind() to 127.0.0.1:9876
  failed, bridge disabled`, while the first instance's bridge keeps
  responding normally.
- Prompted by a user question about whether running more than one
  Debugger GUI at once could conflict on the bridge port.

**繁體中文**

- 修正 `DEBUG_AI_Init()`（`dosbox-src/src/debug/debug_ai.cpp`）在
  `bind()` 前無條件設定 `SO_REUSEADDR` 的問題。在 Windows 上（不同於
  POSIX）這會讓第二個 DOSBox-X-AI 實例成功綁定並監聽同一個第一個實例
  （仍在執行中）已經佔用的 `127.0.0.1:9876`，且沒有明確規則決定 agent
  的連線實際上會連到哪一個實例——這悄悄違反了 bridge 文件宣稱的
  「bind 失敗時會安全停用 bridge」的保證。現在已改成只在 POSIX 上設定
  （`#if !defined(WIN32)`），沿用本專案自己內附的 SDL_net
  （`vs/sdlnet/SDLnetTCP.c`、`vs/sdl2net/SDLnetTCP.c`）針對同一個
  Windows 陷阱早已記載並採用的作法，而非另創新解法。
- 已用兩個同時執行的 `dosbox-x.exe` 實例做過實機驗證：第二個實例的
  `bind()` 現在會失敗，並記錄
  `bind() to 127.0.0.1:9876 failed, bridge disabled`，第一個實例的
  bridge 則持續正常回應。
- 起因是使用者提出「同時開啟一個以上 Debugger GUI 是否會在 bridge
  port 上衝突」的疑問。

---

## Phase 7A — Guest frame capture (2026-08-16)

**English**

- Added `video.frame.capture` to the native AI bridge: captures exactly
  the guest's own rendered frame (never the DOSBox-X window, the host
  desktop, or any other host window) as PNG or raw RGBA8888, without
  stopping guest execution or ever writing to disk.
- Reuses DOSBox-X's own existing screenshot/AVI-recording hook point
  (`RENDER_EndUpdate()` / `CAPTURE_AddImage()`), confirmed
  backend-agnostic (same call site regardless of software/OpenGL/
  Direct3D/Voodoo output) by source investigation before implementation.
- Added `DOSBoxClient.capture_frame()` and the `capture_frame` MCP tool
  (`ai/server.py`) -- returns a directly viewable image for
  `format="png"`, or exact pixel data for `format="rgba"`. Agent-visible
  tool count: 26.
- New error code `FRAME_TOO_LARGE`, with a suggested smaller
  `max_width`/`max_height` in the message, for frames exceeding the
  bridge's payload cap.
- Verified live against a real DOSBox-X instance, including a
  pixel-level cross-check (RGBA output vs. Pillow's decode of the same
  frame's PNG output, 400 sample points, 0 mismatches) that specifically
  catches an R/B channel-order pitfall identified during design.
- See `docs/phase7a-frame-capture-design.md` for the full design and
  verification notes, and `docs/phase7-observability-and-autonomous-control-requirements.md`
  for the broader Phase 7 requirements this is scoped from.

**繁體中文**

- 為原生 AI 橋接層新增 `video.frame.capture`：擷取的是客體自己算出來的
  畫面本身（絕不是 DOSBox-X 視窗、主機桌面，或其他主機視窗），可輸出
  PNG 或原始 RGBA8888，不會停止客體執行，也絕不寫入主機磁碟。
- 重用 DOSBox-X 自己既有的截圖／AVI 錄影掛鉤點
  （`RENDER_EndUpdate()` / `CAPTURE_AddImage()`），實作前已透過原始碼
  調查確認與輸出後端無關（不論 software／OpenGL／Direct3D／Voodoo，
  都是同一個呼叫點）。
- 新增 `DOSBoxClient.capture_frame()` 與 `capture_frame` MCP
  工具（`ai/server.py`）——`format="png"` 會回傳可直接檢視的圖片，
  `format="rgba"` 則回傳精確像素資料。Agent 可見工具數：26 個。
- 新增錯誤代碼 `FRAME_TOO_LARGE`，超過橋接層負載上限時，錯誤訊息會附上
  建議縮小後的 `max_width`／`max_height`。
- 已對真實運行中的 DOSBox-X 做過實機驗證，包含像素級交叉比對（RGBA
  輸出 vs. 同一畫面 PNG 輸出經 Pillow 解碼後的結果，400 個取樣點、0 個
  不一致）——這正是設計階段就點名的 R/B 色版順序風險的驗證。
- 完整設計與驗證細節見 `docs/phase7a-frame-capture-design.md`；此功能
  所依據的完整 Phase 7 需求見
  `docs/phase7-observability-and-autonomous-control-requirements.md`。

---

## Phase 6B — Keyboard & mouse input injection (2026-08-16)

**English**

- Added `input.key.down/up/tap` and `input.mouse.move_relative/
  button.set/button.click/release_all` to the native AI bridge --
  keyboard/mouse input delivered through the SAME internal path DOSBox-X's
  own SDL event handlers use (`KEYBOARD_AddKey()`, `Mouse_CursorMoved()`,
  `Mouse_ButtonPressed()`/`Mouse_ButtonReleased()`). No `SendKeys`, window
  focus/handle manipulation, or GUI automation anywhere in this path.
- Input injection only reaches the guest while it is actually running
  (not stopped), mirroring `execution.pause`'s existing
  `Normal_Loop()`-hook architecture rather than the request queue used by
  every earlier method.
- Stuck-key/button safety: held keys/buttons are tracked per connection
  and automatically released if the connection is lost (client crash,
  session timeout) before an explicit release -- verified live by holding
  a key down and abruptly disconnecting, then confirming the bridge and a
  fresh connection both stayed healthy afterward.
- `key` names are a fixed, auditable whitelist (the standard US 104-key
  layout) -- not free text or raw scan codes.
- Wired into `DOSBoxClient` and the `ai/server.py` MCP tool surface
  (bringing the tool count to 25 before Phase 7A's addition).
- See `docs/phase6b-input-injection-design.md` for the full design.

**繁體中文**

- 為原生 AI 橋接層新增 `input.key.down/up/tap` 與
  `input.mouse.move_relative`／`button.set`／`button.click`／
  `release_all`——鍵盤／滑鼠輸入是透過與 DOSBox-X 自己的 SDL
  事件處理常式完全相同的內部路徑送出（`KEYBOARD_AddKey()`、
  `Mouse_CursorMoved()`、`Mouse_ButtonPressed()`／`Mouse_ButtonReleased()`），
  整條路徑上沒有 `SendKeys`、視窗焦點／控制代碼操作，也沒有 GUI 自動化。
- 輸入注入只有在客體真正執行中（非停止狀態）才能送達，沿用的是
  `execution.pause` 既有的 `Normal_Loop()` 掛鉤架構，而不是先前每個方法
  都用的請求佇列機制。
- 按鍵／按鈕卡住的防護：每個連線都會追蹤目前按住的按鍵／按鈕，若連線
  在明確釋放前遺失（客戶端當掉、工作階段逾時），會自動釋放——已透過
  實機測試驗證：按住一個按鍵後突然斷線，之後橋接層與新連線都維持正常。
- `key` 的名稱是固定、可稽核的白名單（標準美式 104 鍵配列），不是自由
  文字或原始 scan code。
- 已接上 `DOSBoxClient` 與 `ai/server.py` 的 MCP 工具介面（在 Phase 7A
  加入前，工具數來到 25 個）。
- 完整設計見 `docs/phase6b-input-injection-design.md`。

---

## Phase 6A — Real-mode & protected-mode memory watchpoints (2026-08-16)

**English**

- Confirmed, committed, and wired into the MCP tool surface:
  `set_real_memory_breakpoint()`/`set_protected_memory_breakpoint()`
  (native `breakpoint.memory.real.set`/`breakpoint.memory.set`), watching
  one byte at a real-mode `SEG:OFFSET` or protected-mode
  `SELECTOR:OFFSET` address and stopping execution after it changes,
  using the native debugger's own BPPM mechanism (heavy-debug builds
  only).
- `list_breakpoints()` now reports each breakpoint's `type` ("code",
  "memory", or "protected_memory") instead of silently omitting
  non-code breakpoints.
- This work existed in the submodule but was uncommitted at the start of
  this session; committed here along with the Python client wrapper and
  MCP tool registration that had never been wired up.

**繁體中文**

- 確認、commit，並接上 MCP 工具介面：
  `set_real_memory_breakpoint()`／`set_protected_memory_breakpoint()`
  （原生方法 `breakpoint.memory.real.set`／`breakpoint.memory.set`），
  監看 real-mode `SEG:OFFSET` 或 protected-mode `SELECTOR:OFFSET`
  位址上的一個位元組，該值改變後就停止執行，使用的是原生除錯器自己的
  BPPM 機制（僅限 heavy-debug 建置）。
- `list_breakpoints()` 現在會回報每個中斷點的 `type`（`"code"`、
  `"memory"` 或 `"protected_memory"`），不再悄悄跳過非程式碼中斷點。
- 這部分工作在本次 session 開始前就已經在子模組中實作完成，但尚未
  commit；本次一併 commit，並補上先前從未接上的 Python client 包裝與
  MCP 工具註冊。

---

## Documentation & tooling / 文件與工具（2026-08-16）

**English**

- Added `AGENT_GUIDE.md` / `AGENT_GUIDE.zh-TW.md`: the reference for an
  AI agent connecting to this project -- required environment,
  installation/build steps, a full tool reference table, the native
  error code catalog, and example workflows.
- Added `docs/phase6-test-plan.md`: concrete (not yet implemented)
  automated test cases for Phase 6A/6B.
- Added `docs/phase7-observability-and-autonomous-control-requirements.md`
  (the Phase 7 requirements draft) and
  `docs/case-study-dark-sun-gpli-debugging.md` (a worked example using
  the memory-watchpoint tools).
- `.gitignore`: added a `/build-*/` pattern for local scratch deployment
  copies of the built binary (e.g. `build-memory/`, `build-selector/`),
  never meant to be committed.

**繁體中文**

- 新增 `AGENT_GUIDE.md`／`AGENT_GUIDE.zh-TW.md`：給連線到本專案的 AI
  agent 使用的參考手冊——所需環境、安裝／建置步驟、完整工具參考表、
  原生錯誤代碼對照，以及範例工作流程。
- 新增 `docs/phase6-test-plan.md`：Phase 6A／6B 具體（尚未實作）的
  自動化測試案例。
- 新增 `docs/phase7-observability-and-autonomous-control-requirements.md`
  （Phase 7 需求草案）與 `docs/case-study-dark-sun-gpli-debugging.md`
  （一篇使用記憶體監看點工具的實戰案例）。
- `.gitignore`：新增 `/build-*/` 規則，排除本機用來測試的建置成果
  臨時複本（例如 `build-memory/`、`build-selector/`），這些從來就不該
  被 commit。
