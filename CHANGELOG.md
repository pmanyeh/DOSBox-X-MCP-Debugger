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

## Phase 8E/8F — synthetic mouse writes now update motion counters and take effect without host capture (2026-09-29)

**English**

- Live testing against a real game found two related defects in how
  `move_mouse_absolute()`/`click_at()` (the AI bridge's synthetic
  absolute mouse writes, `src/debug/debug_ai.cpp`) interact with
  DOSBox-X's guest-facing mouse emulation (`src/ints/mouse.cpp`,
  `include/mouse.h`):
  - **Phase 8E**: an absolute write only ever updated `mouse.x`/`mouse.y`
    (read by INT 33h `AH=03h`, "get position"). A guest that instead
    polls `mouse.mickey_x`/`mickey_y` (`AH=0Bh`, "read motion counters")
    perceived no movement at all, no matter what position the bridge
    wrote -- confirmed live against a game whose on-screen cursor sprite
    never moved across repeated calls to visibly different positions,
    even with the mouse captured. Fixed by adding
    `Mouse_AddNormalizedMickeys()` (`mouse.cpp`/`mouse.h`): given the
    normalized-position delta since the previous bridge write (tracked
    via the already-existing `g_lastGuestX`/`Y` state in
    `debug_ai.cpp`), it scales by the driver's own `mouse.max_x`/`max_y`
    (the same values `Mouse_CursorMoved()`'s own absolute branch uses)
    and accumulates into `mouse.mickey_x`/`mickey_y` with the identical
    wraparound clamp `Mouse_CursorMoved()` itself uses, so a guest
    reading motion counters cannot tell the difference from genuine
    relative motion that happened to add up to the same delta. No mickey
    delta is generated for the first-ever write in a session (nothing to
    diff against yet), matching how a real mouse cannot report motion
    before its first sample.
  - **Phase 8F**: `DEBUG_AI_CheckPendingInput()`'s absolute-write branch
    calls `Mouse_CursorMoved()`, but under the default
    `mouse_emulation=locked` a second, later check in the same function
    overwrites `mouse.x`/`y` with a host-cursor proxy whenever
    `user_cursor_locked` is false. That flag is normally kept in sync
    with real host mouse capture, but only by `src/gui/sdlmain.cpp`'s
    real SDL mouse-motion event handler -- which the bridge's synthetic
    writes never trigger, so it silently stayed at its process-start
    default (`false`) forever, regardless of how many times
    `set_mouse_capture(true)` was called. Confirmed live: an isolated
    test program polling INT 33h `AH=03h` read back the same fixed,
    unrelated position on every poll regardless of what
    `move_mouse_absolute()`/`click_at()` sent, with or without capture.
    Fixed by forcing `user_cursor_locked = true` for the duration of the
    `Mouse_CursorMoved()` call in `debug_ai.cpp` and restoring its prior
    value immediately after, rather than permanently altering a flag
    that three other files (`bios.cpp`, `serialmouse.cpp`,
    `keyboard.cpp`) also read for unrelated purposes.
  - Both fixes live entirely in `dosbox-src` (native bridge); no `ai/`
    (Python MCP layer) changes were needed, since the MCP tool
    surface/parameters for `move_mouse_absolute`/`click_at` are
    unchanged -- only what the native write does internally.

**繁體中文**

- 針對真實遊戲的實機測試發現，`move_mouse_absolute()`／`click_at()`
  （AI 橋接層的合成絕對滑鼠寫入，位於 `src/debug/debug_ai.cpp`）與
  DOSBox-X 面向客體的滑鼠模擬（`src/ints/mouse.cpp`、
  `include/mouse.h`）之間有兩個相關的缺陷：
  - **Phase 8E**：絕對寫入只會更新 `mouse.x`／`mouse.y`（由 INT 33h
    `AH=03h`「取得位置」讀取）。如果客體改讀 `mouse.mickey_x`／
    `mickey_y`（`AH=0Bh`「讀取移動計數器」），不管橋接層寫入什麼位置，
    客體都感覺不到任何移動——這在實機測試中已確認：即使滑鼠已捕捉，
    重複呼叫到明顯不同的位置，遊戲畫面上的游標圖示也完全不動。修正
    方式是新增 `Mouse_AddNormalizedMickeys()`（`mouse.cpp`／
    `mouse.h`）：依照自上次橋接層寫入以來的正規化位置差（透過
    `debug_ai.cpp` 既有的 `g_lastGuestX`／`Y` 狀態追蹤），乘上驅動程式
    自己的 `mouse.max_x`／`max_y`（跟 `Mouse_CursorMoved()` 本身絕對
    座標分支所用的值相同），再用 `Mouse_CursorMoved()` 自己那套折返
    (wraparound) clamp 累加進 `mouse.mickey_x`／`mickey_y`，讓讀取移動
    計數器的客體無法分辨這跟「剛好加總出同樣差值的真實相對移動」有
    什麼不同。一個 session 裡的第一次寫入不會產生 mickey 差值（還沒有
    前一筆可比對），這跟真實滑鼠在第一次取樣之前無法回報移動的行為
    一致。
  - **Phase 8F**：`DEBUG_AI_CheckPendingInput()` 裡處理絕對寫入的分支
    會呼叫 `Mouse_CursorMoved()`，但在預設的 `mouse_emulation=locked`
    下，同一個函式裡稍後還有第二段檢查，只要 `user_cursor_locked` 為
    false，就會用主機游標的代理值覆寫 `mouse.x`／`y`。這個旗標平常
    只由 `src/gui/sdlmain.cpp` 真正的 SDL 滑鼠移動事件處理器同步——而
    橋接層的合成寫入從不會觸發它，導致它從程式啟動起就一直維持預設值
    （`false`），不管呼叫了幾次 `set_mouse_capture(true)` 都一樣。實機
    確認：一支獨立的測試程式持續輪詢 INT 33h `AH=03h`，不管
    `move_mouse_absolute()`／`click_at()` 送出什麼、也不管有沒有捕捉，
    每次讀回的都是同一個固定、不相關的位置。修正方式是在
    `debug_ai.cpp` 呼叫 `Mouse_CursorMoved()` 期間暫時把
    `user_cursor_locked` 強制設為 `true`，呼叫結束後立刻還原成原本的
    值，而不是永久改動這個另外三個檔案（`bios.cpp`、
    `serialmouse.cpp`、`keyboard.cpp`）也會因為不相關用途而讀取的
    旗標。
  - 這兩個修正完全位於 `dosbox-src`（原生橋接層）之內；`ai/`（Python
    MCP 層）不需要任何改動，因為 `move_mouse_absolute`／`click_at` 的
    MCP 工具介面／參數完全沒變——改變的只是原生寫入內部的實際行為。

---

## Documentation clarification — `guest_pixels` vs. native video-mode resolution (2026-09-19)

**English**

- A downstream integration reported that the bridge "reports 640x400
  but the effective game screen is 320x200," requiring their own
  tooling to double every mouse coordinate before calling
  `move_mouse_absolute`/`click_at`. Investigated by re-deriving the
  exact arithmetic against `dosbox-src/src/ints/mouse.cpp` (DOS's real
  INT 33h mouse-driver coordinate convention) rather than assuming --
  **not a code bug**. For Mode 13h, DOSBox-X's own display layer
  doubles both axes for on-screen rendering (`render.src.dblw`/`dblh`),
  so `get_mouse_capture()`'s `guest_width`/`guest_height` correctly
  reports 640x400 -- the RENDERED/screenshot size, matching
  `capture_frame()`'s own output, exactly as designed
  (`docs/phase7b-mouse-capture-and-absolute-input-design.md`). Working
  through the exact fractions in `ResolveAbsoluteTarget()`/
  `Mouse_CursorMoved()` confirms both axes resolve correctly and
  proportionally when the input coordinates are genuinely
  screenshot-relative. The downstream integration's coordinates instead
  came from analysis against the game's native 320x200 resolution
  (e.g. reading VRAM directly), so passing them straight through as
  `"guest_pixels"` landed at exactly half the intended position on both
  axes -- a caller-side coordinate-space mismatch, not a defect in the
  conversion math.
- Resolution: documentation-only, no code changed and no
  `dosbox-x.exe` rebuild needed. `AGENT_GUIDE.md`/`.zh-TW.md` (the
  "Mouse capture & absolute positioning" section),
  `ai/dosbox_client.py`'s `get_mouse_capture()`/`move_mouse_absolute()`
  docstrings, `ai/server.py`'s corresponding MCP tool docstrings, and
  `docs/phase7b-mouse-capture-and-absolute-input-design.md` (new "Known
  caveat" subsection) now state explicitly that `guest_width`/
  `guest_height` is the RENDERED size, which can be a multiple of the
  guest video mode's nominal resolution for low-resolution modes, and
  that native-resolution-derived coordinates must be scaled to the
  actual reported `guest_width`/`guest_height` before use.

**繁體中文**

- 有下游整合方回報，橋接層「回報 640×400，但有效遊戲畫面是
  320×200」，導致他們自己的工具必須在呼叫 `move_mouse_absolute`／
  `click_at` 之前把每個滑鼠座標都放大兩倍。這次調查是直接對照
  `dosbox-src/src/ints/mouse.cpp`（DOS 真正的 INT 33h 滑鼠驅動座標慣例）
  重新推導精確的分數運算，而不是用猜的——**結論是這不是程式碼的
  bug**。對 Mode 13h 而言，DOSBox-X 自己的顯示層為了螢幕顯示，會把
  兩個軸都放大一倍（`render.src.dblw`／`dblh`），所以
  `get_mouse_capture()` 回報的 `guest_width`／`guest_height` 是 640×400
  完全正確——這是**渲染後（螢幕截圖）的尺寸**，跟 `capture_frame()`
  的輸出一致，完全符合當初的設計
  （`docs/phase7b-mouse-capture-and-absolute-input-design.md`）。仔細
  算過 `ResolveAbsoluteTarget()`／`Mouse_CursorMoved()` 裡的精確分數後
  確認：只要輸入座標真的是「螢幕截圖相對」座標，兩個軸都能正確、等比例
  地換算。而這個下游整合方的座標，其實是依照遊戲的原生 320×200 解析度
  分析出來的（例如直接讀 VRAM），把這種原生解析度的數字直接當成
  `"guest_pixels"` 送出去，兩個軸自然都會落在預期位置的一半處——這是
  呼叫端座標空間認知落差，不是換算公式本身的缺陷。
- 處理方式：純文件修正，沒有改動任何程式碼，也不需要重新編譯
  `dosbox-x.exe`。`AGENT_GUIDE.md`／`.zh-TW.md`（「滑鼠捕獲狀態與絕對
  座標定位」章節）、`ai/dosbox_client.py` 的 `get_mouse_capture()`／
  `move_mouse_absolute()` docstring、`ai/server.py` 對應的 MCP 工具
  docstring，以及 `docs/phase7b-mouse-capture-and-absolute-input-design.md`
  （新增的「已知注意事項」小節），現在都明確寫出 `guest_width`／
  `guest_height` 是**渲染後**的尺寸，在低解析度模式下可能是遊戲原生
  解析度的倍數，且依照原生解析度算出來的座標，必須先換算成實際回報的
  `guest_width`／`guest_height` 比例，才能拿去使用。

---

## Phase 8C — agent-side reverse-engineering tools: memory search, knowledge store, call-stack unwinding, control-flow graph (2026-09-19)

**English**

- Added four agent-side capabilities aimed at closing the gap between
  "inspect one instant of the guest" (everything through Phase 8A) and
  "accumulate reverse-engineering knowledge across a session" -- see
  `docs/phase8c-agent-side-analysis-tools-design.md` for the full design
  and `ai/Phase8C.md` for exact scope/status. None of these are native
  bridge methods and none required a `dosbox-x.exe` rebuild: all four are
  built entirely by composing the existing native protocol
  (`memory.read`, `code.disassemble`, `cpu.get`) from the Python side, an
  explicit architecture decision to avoid a second CPU/disassembler/
  memory-reading mechanism.
- **`memory_search`** (`ai/analysis.py`): scans real, running DOSBox-X
  guest memory for a byte pattern (with `??`/`?`/`None` wildcards) or an
  ASCII string (optionally case-insensitive), starting at a "SEG:OFF"
  address over up to the entire real-mode address space (0x100000
  bytes). Crosses segment boundaries by always reading to the end of the
  current segment first, then stepping the segment forward by one full
  0x10000-byte chunk (0x1000 paragraphs) per subsequent read -- this can
  never trigger the native bridge's own 16-bit offset wraparound within
  one `memory.read` call. A match straddling a chunk boundary is found
  via a sliding-window carry of the previous chunk's tail bytes, and
  reported using a canonicalized `linear_address >> 4 : linear_address &
  0xF` address (unambiguous even when the match's "natural" segment
  would need an offset above 0xFFFF). Guest memory the native bridge
  reports `MEMORY_ERROR` for while scanning is skipped and reported
  under `"unreadable_regions"`, never treated as zero bytes or
  fabricated as a match, per this project's "no fake data" rule.
- **A persistent symbol/annotation knowledge store** (`ai/knowledge.py`'s
  `KnowledgeStore`, exposed as eight MCP tools: `set_symbol`/
  `get_symbol`/`delete_symbol`/`list_symbols`, `set_comment`/
  `get_comment`, `add_xref`/`list_xrefs`): lets an agent name an address,
  attach a free-text comment, or record a cross-reference, persisted to
  `ai/knowledge.local.json` (git-ignored) across sessions. Addresses are
  canonicalized the same way as `memory_search()`'s match addresses, so
  any "SEG:OFF" spelling of the same linear address finds the same
  entry. Lives entirely on the agent side -- never inside DOSBox-X or the
  native bridge -- so none of its eight tools are wrapped in
  `_guarded_native()`; bad input raises a plain `ValueError`, matching
  `write_io_port()`'s existing convention.
- **`get_call_stack`** (`ai/analysis.py`): walks the real-mode `SS:BP`
  frame-pointer chain from the debugger's current stopped position (one
  `cpu.get` call plus repeated `read_memory` calls), the same manual
  technique a human doing real-mode stack unwinding already uses. Stated
  limitation: assumes a standard `PUSH BP`/`MOV BP,SP` prologue and NEAR
  (same-segment) `CALL`s, matching this project's own DOS test programs
  -- a FAR call's 4-byte return address would be misread as two
  unrelated 2-byte fields, since 16-bit real-mode code has no formal
  frame-pointer metadata to consult instead. Stops once a saved `BP` is
  not strictly greater than the current frame's `BP` (real-mode stacks
  grow downward) or on unmapped stack memory.
- **`build_control_flow_graph`** (`ai/analysis.py`): recursively walks
  `code.disassemble` from a starting address, splitting a new block at
  every resolvable near `JMP`/`Jcc`/`CALL`/`LOOP*`/`JCXZ` and following
  its target(s) -- no second disassembler. Before writing the text
  parser, `dosbox-src/src/debug/debug_disasm.cpp` was read directly to
  confirm the exact rendering of a resolvable near-branch operand
  (`case 'J'`: an 8-hex-digit value with no segment/colon, e.g. `"jmp
  0000E05B"` -- not a `SEG:OFF` pair), so the parser is grounded in the
  actual disassembler source rather than a guess. A far/indirect
  transfer, `RET`/`IRET`, or `INT` ends a block with its
  `"unresolved_transfer"` field naming which kind stopped the walk
  there ("indirect_or_far_transfer"/"return"/"software_interrupt")
  rather than fabricating a target. Stated limitation: single-pass, not
  a full two-pass basic-block partition -- a later-discovered jump
  target landing inside an earlier block's already-covered range
  produces an overlapping second block rather than a retroactive split.
- Tested with 35 new unit tests: `tests/test_analysis.py` (23 total --
  11 for `memory_search`, 5 for `get_call_stack` against a `StubClient`
  extended with a configurable `get_cpu_state()`, 7 for
  `build_control_flow_graph` against a new `CfgStubClient` that models
  physically-contiguous instruction runs the way a real `disassemble()`
  call actually decodes them, plus parameter-validation tests) and
  `tests/test_knowledge.py` (12 -- canonical-address lookup equivalence,
  delete/list, comments, xref idempotency and direction filtering,
  invalid `kind`/`direction`, and a real save-then-reload persistence
  round trip). No live DOSBox-X instance required for any of them,
  matching `tests/test_debugger.py`'s existing fake-backend testing
  pattern. Existing `tests/test_debugger.py` regression (17 tests)
  reconfirmed alongside them.
- Interrupt-level call tracing (exposing `BPINT`-equivalent tracing
  through the MCP layer) remains deliberately deferred to a separate
  Phase 8D, since -- unlike this phase's four items -- it requires a
  native bridge change and a `dosbox-x.exe` rebuild. `vga.watch_writes`
  remains the separately reserved "Phase 8B" from the Phase 8A entry
  below and is untouched here.
- `AGENT_GUIDE.md`/`.zh-TW.md` and `README.md`/`.zh-TW.md` updated to 50
  tools, with `memory_search`/`get_call_stack`/`build_control_flow_graph`
  added to the "Memory & disassembly" tool table, a new "Agent-side
  knowledge store" section for the eight knowledge tools, and an updated
  Phase 8C capability row.

**繁體中文**

- 新增四項 agent 端能力，目標是補上「檢視客體某一瞬間的狀態」（Phase
  8A 為止的一切）與「在一次工作階段中持續累積逆向工程知識」之間的落差
  ——完整設計見 `docs/phase8c-agent-side-analysis-tools-design.md`，確切
  範疇／狀態見 `ai/Phase8C.md`。這四項都不是原生 bridge 方法，也都不需要
  重新編譯 `dosbox-x.exe`：全部都是在 Python 端重複組合既有的原生協定
  （`memory.read`、`code.disassemble`、`cpu.get`）而成，這是一個明確的
  架構決定，目的是避免引入第二套 CPU／反組譯／記憶體讀取機制。
- **`memory_search`**（`ai/analysis.py`）：在真實、正在執行中的 DOSBox-X
  客體記憶體裡，從一個 "SEG:OFF" 位址開始，搜尋一段位元組樣式（支援
  `??`／`?`／`None` 萬用字元）或一段 ASCII 字串（可選擇不分大小寫），
  搜尋範圍最大可涵蓋整個 real-mode 位址空間（0x100000 位元組）。跨越
  segment 邊界的做法是：一律先讀到目前 segment 的結尾，接著每次都以完整
  一個 0x10000 位元組的區塊（0x1000 個 paragraph）往前推進 segment——這樣
  就不可能在單次 `memory.read` 呼叫中觸發原生 bridge 自己的 16-bit
  offset 折返。橫跨區塊邊界的比對，透過保留上一個區塊尾端位元組的滑動
  視窗（carry）來偵測，回報時一律轉換成正規化的 `linear_address >> 4 :
  linear_address & 0xF` 位址（即使比對結果「自然的」segment 會需要超過
  0xFFFF 的 offset，這種表示法依然明確無歧義）。掃描過程中若原生 bridge
  回報 `MEMORY_ERROR`（記憶體未對應／無法存取），該區塊會被跳過並記錄在
  `"unreadable_regions"` 裡，不會被當成全零位元組，也不會被虛構成比對
  結果，符合本專案「不使用虛構資料」的原則。
- **一個持久化的符號／註記知識庫**（`ai/knowledge.py` 的
  `KnowledgeStore`，以八個 MCP 工具暴露：`set_symbol`／`get_symbol`／
  `delete_symbol`／`list_symbols`、`set_comment`／`get_comment`、
  `add_xref`／`list_xrefs`）：讓 agent 可以替一個位址命名、附加自由文字
  註記，或記錄交叉引用，並跨工作階段持久化到 `ai/knowledge.local.json`
  （已加入 `.gitignore`）。位址正規化方式與 `memory_search()` 的比對結果
  相同，所以同一個 linear 位址的任何 "SEG:OFF" 寫法都能查到同一筆資料。
  完全存在於 agent 端——絕不進入 DOSBox-X 或原生 bridge——所以這八個工具
  都沒有包在 `_guarded_native()` 裡；不合法的輸入會產生一般的
  `ValueError`，沿用 `write_io_port()` 既有的慣例。
- **`get_call_stack`**（`ai/analysis.py`）：從除錯器目前的停止位置開始，
  走訪 real-mode 的 `SS:BP` 堆疊鏈（一次 `cpu.get` 呼叫加上重複的
  `read_memory` 呼叫），這正是人類手動進行 real-mode 堆疊回溯時使用的
  技巧。已聲明的限制：假設標準的 `PUSH BP`／`MOV BP,SP` 前導碼與 NEAR
  （同 segment）的 `CALL`，這與本專案自己的 DOS 測試程式一致——FAR call
  的 4 位元組返回位址會被誤讀成兩個不相關的 2 位元組欄位，因為 16-bit
  real-mode 程式碼並沒有正式的 frame-pointer 中繼資料可供分辨這兩種情況。
  當某個保存的 `BP` 不嚴格大於目前這一層的 `BP` 時（real-mode 堆疊往
  低位址成長）就會停止，或是遇到無法存取的堆疊記憶體時也會停止。
- **`build_control_flow_graph`**（`ai/analysis.py`）：從一個起始位址開始
  遞迴走訪 `code.disassemble`，在每個可解析的 near `JMP`／`Jcc`／
  `CALL`／`LOOP*`／`JCXZ` 處分割出新的區塊並跟隨其目標——沒有第二套
  反組譯器。在寫文字解析器之前，直接讀取了 `dosbox-src/src/debug/
  debug_disasm.cpp` 原始碼，確認可解析的 near 分支運算元的確切呈現方式
  （`case 'J'`：一個 8 位十六進位數字，沒有 segment、沒有冒號，例如
  `"jmp 0000E05B"`——不是 "SEG:OFF" 的形式），讓解析邏輯建立在真實的
  反組譯器原始碼上，而不是用猜的。far／間接跳轉、`RET`／`IRET` 或 `INT`
  都會結束一個區塊，其 `"unresolved_transfer"` 欄位會註明是哪一種
  （`"indirect_or_far_transfer"`／`"return"`／`"software_interrupt"`）
  中斷了走訪，而不是虛構一個目標。已聲明的限制：這是單一遍歷，不是完整
  的兩遍基本區塊切割——如果之後才發現的跳躍目標，落在某個較早的區塊
  已經涵蓋的範圍中間，會產生一個內容重疊的第二個區塊，而不是回頭去
  切割前一個區塊。
- 新增 35 個單元測試：`tests/test_analysis.py`（共 23 個——11 個測試
  `memory_search`、5 個針對擴充了可設定 `get_cpu_state()` 的
  `StubClient` 測試 `get_call_stack`、7 個針對新的 `CfgStubClient`
  測試 `build_control_flow_graph`——`CfgStubClient` 模擬的是實體上連續
  的指令序列，就跟真正的 `disassemble()` 呼叫解碼記憶體的方式一樣，
  另外還有參數驗證測試）與 `tests/test_knowledge.py`（12 個——跨不同
  位址表示法的正規化查詢、刪除／列表、註記、xref 冪等性與方向篩選、
  不合法的 `kind`／`direction`，以及一次真正的「儲存後重新載入」持久化
  往返測試）。全部都不需要真正執行中的 DOSBox-X，沿用
  `tests/test_debugger.py` 既有的「針對假後端測試」慣例。同時重新確認
  既有的 `tests/test_debugger.py` 回歸測試（17 項）仍然通過。
- 中斷層級的呼叫追蹤（在 MCP 層暴露相當於 `BPINT` 的追蹤能力）仍然刻意
  延後到另一個獨立的 Phase 8D，因為——與本階段這四項不同——它需要修改
  原生 bridge 並重新編譯 `dosbox-x.exe`。`vga.watch_writes` 仍然是下面
  Phase 8A 條目中另外保留的「Phase 8B」，本次未觸碰。
- `AGENT_GUIDE.md`／`.zh-TW.md` 與 `README.md`／`.zh-TW.md` 已更新為 50
  個工具，在「記憶體與反組譯」工具表中加入
  `memory_search`／`get_call_stack`／`build_control_flow_graph`，新增
  一個「Agent 端知識庫」章節說明八個知識庫工具，並更新了 Phase 8C
  能力列表。

---

## Phase 8A — `vga.snapshot`, a side-effect-free VGA VRAM read (2026-09-18)

**English**

- Added `vga.snapshot` to the native AI bridge (`debug_ai.cpp`) and a
  matching `vga_snapshot` MCP tool, directly answering client feedback on
  the Mode X "bottom 30 lines get cleared, owned path doesn't repaint"
  investigation: the most-needed missing piece was a VRAM read that
  cannot itself change the guest state being diagnosed. `vga.snapshot`
  reads one or more (plane, offset, length) regions, the VGA latch, and
  the Sequencer/Graphics Controller/CRTC register files, all from one
  consistent instant, entirely bypassing the CPU's `A000:xxxx` read path
  (`mem_readb_checked`/any `PageHandler`) that `read_memory` uses. That
  distinction matters because a normal CPU-visible byte read at
  `A000:xxxx` has a genuine hardware side effect in GC read-mode 0: it
  latches all four planes into `vga.latch` -- so a diagnostic
  `read_memory` call could silently corrupt the very latch state a Mode X
  `write_mode 1` operation depends on if the guest resumes afterward.
  `vga.snapshot` instead reads `vga.mem.linear`/`vga.latch.d`/
  `vga.seq`/`vga.gfx`/`vga.crtc` directly as plain field reads, so it
  cannot mutate the latch, any VGA register, CPU state, guest memory, or
  execution position, and never needs the read plane switched first
  (`write_io_port` to `3CE`/`3CF`) -- all four planes come back from the
  same call regardless of which plane was last selected.
- Reuses the same plane-interleaved-dword VRAM layout every EGA/VGA-family
  card's planar memory already has (`vga.mem.linear[offset*4 + plane]`,
  confirmed against the two actual planar read/write call sites in
  `vga_memory.cpp`) -- a physical memory-bus property independent of the
  current video mode, so no per-mode special-casing was needed. Gated on
  `IS_EGAVGA_ARCH`; any other machine type (CGA/Hercules/Tandy/PCjr/PC-98,
  whose VRAM is laid out differently) is rejected with a dedicated
  `VGA_SNAPSHOT_UNSUPPORTED` error rather than returning meaningless
  bytes. Reuses the existing `g_requestQueue`/`DEBUG_AI_Poll()` mechanism
  (like `memory.read`/`io.write`), so it can only ever execute while the
  debugger is genuinely stopped -- the CPU cannot run between reading
  plane 0 and plane 3, or between the latch and the register dump.
- See `docs/phase8a-vga-snapshot-design.md` for the full design (request/
  response shape, the plane-interleaved memory layout, and why the
  request must be answered only while stopped) and `AGENT_GUIDE.md`/
  `.zh-TW.md` for the tool reference (39 tools total).
- Deliberately does not implement `vga.watch_writes` (a real VRAM-write
  breakpoint keyed on plane+offset, requested as the client's Priority 2)
  -- the client's own feedback says Priority 1 alone is sufficient to
  substantially unblock the current diagnosis without needing Priority 2
  first, so it is tracked as a follow-up phase (8B) rather than built now.
- Verified against a live, running `dosbox-x.exe` (rebuilt
  `dosbox-x.vcxproj`, 0 errors, `-break-start drive_c\STEP.COM`): calling
  `vga.snapshot` twice in a row while stopped returned bit-for-bit
  identical `latch`/register values both times, `continue_execution`
  afterward behaved normally, and the debugger's own `location` was
  unchanged across both calls -- confirming the call has zero observable
  side effect on guest/debugger state. The client's own motivating region
  shapes (bottom 30 lines of two Mode X pages, offsets `0x3520`/`0x7520`,
  2,400 bytes each, all four planes; plus both full pages at
  `0x0000`/`0x4000`, 16,000 bytes each -- 16 regions in one call) came
  back with the correct `returned_length` for each, and a deliberately
  overrunning region correctly clamped (`returned_length` < requested,
  never an error). `STEP.COM` is this project's own minimal test binary,
  stopped at its entry point in default text mode, not the client's own
  Mode X game -- the actual "does the on-screen picture stay identical
  around a real Mode X repaint" comparison from the design doc's
  verification plan still needs to be run against that game directly.

**繁體中文**

- 在原生 AI bridge（`debug_ai.cpp`）新增 `vga.snapshot`，並對應加上
  `vga_snapshot` 這個 MCP 工具，直接回應客戶對 Mode X「畫面最下方 30 列
  被清掉、owned 路徑沒有同步重繪」這個調查案的回饋：目前最缺的一塊，就
  是一個「診斷本身不會改變 guest 狀態」的 VRAM 讀取方式。`vga.snapshot`
  會在同一個一致的時間點，讀取一或多個 (plane、offset、length) 區段、
  VGA latch，以及 Sequencer／Graphics Controller／CRTC 的暫存器組，完全
  繞過 `read_memory` 所使用的 CPU `A000:xxxx` 讀取路徑
  （`mem_readb_checked`／任何 `PageHandler`）。這個區別很關鍵：在 GC
  read-mode 0 底下，一般 CPU 可見的 `A000:xxxx` 位元組讀取本身就有真實
  硬體副作用——會把四個 plane 都鎖進 `vga.latch`——所以一次診斷性質的
  `read_memory` 呼叫，可能就悄悄破壞了 Mode X `write_mode 1` 操作在
  guest 繼續執行後所依賴的 latch 狀態。`vga.snapshot` 改成直接讀取
  `vga.mem.linear`／`vga.latch.d`／`vga.seq`／`vga.gfx`／`vga.crtc` 這些
  純欄位，因此不可能改動 latch、任何 VGA 暫存器、CPU 狀態、guest 記憶體
  或執行位置，也完全不需要事先切換 read plane（`write_io_port` 寫
  `3CE`/`3CF`）——不管最後選到哪個 plane，四個 plane 都會在同一次呼叫中
  回傳。
- 沿用每一張 EGA/VGA 家族顯示卡 planar 記憶體本來就有的「四個 plane 交錯
  存放」布局（`vga.mem.linear[offset*4 + plane]`，已對照 `vga_memory.cpp`
  中兩個實際的 planar 讀寫呼叫點確認過）——這是記憶體匯流排本身的物理
  特性，與目前的顯示模式無關，因此不需要針對個別模式另外處理。以
  `IS_EGAVGA_ARCH` 做為前提條件；其餘機型（CGA／Hercules／Tandy／PCjr／
  PC-98，其 VRAM 布局完全不同）一律以專屬的 `VGA_SNAPSHOT_UNSUPPORTED`
  錯誤拒絕，而不是回傳沒有意義的位元組。沿用既有的
  `g_requestQueue`/`DEBUG_AI_Poll()` 機制（與 `memory.read`／`io.write`
  相同），因此永遠只會在除錯器真正停止時才會執行——CPU 不可能在讀取
  plane 0 與 plane 3 之間、或是在讀 latch 與讀暫存器之間跑動。
- 完整設計（請求／回應格式、plane 交錯記憶體布局，以及為何必須只在
  停止時回應）請見 `docs/phase8a-vga-snapshot-design.md`；工具參考則在
  `AGENT_GUIDE.md`/`.zh-TW.md`（共 39 個工具）。
- 刻意沒有實作 `vga.watch_writes`（依 plane+offset 監看真正 VRAM 寫入的
  breakpoint，也就是客戶回饋中的優先順序二）——客戶自己的回饋已經說明，
  光是優先順序一就足以大幅改善目前的診斷，不需要先做優先順序二，因此
  這裡先不實作，列為後續 Phase（8B）的追蹤項目。
- 已對著真正在跑的 `dosbox-x.exe` 驗證（重建 `dosbox-x.vcxproj`，0 錯
  誤，以 `-break-start drive_c\STEP.COM` 啟動）：在除錯器停止狀態下連續
  呼叫兩次 `vga.snapshot`，兩次回傳的 `latch`／暫存器值逐位元組完全
  相同，之後呼叫 `continue_execution` 行為也正常，兩次呼叫之間除錯器
  自己回報的 `location` 也完全沒變——確認這個呼叫對 guest／除錯器狀態
  沒有任何可觀察的副作用。客戶自己提出的區段形狀（兩個 Mode X 頁面最
  下方 30 列，plane offset 分別為 `0x3520`／`0x7520`，各 2,400 bytes，
  四個 plane 都要；以及兩個完整頁面 `0x0000`／`0x4000`，各 16,000
  bytes——合計 16 個區段一次呼叫）都各自回報正確的 `returned_length`，
  故意讓某個區段超出範圍時也正確地被截斷（`returned_length` 小於請求
  值，而不是報錯）。`STEP.COM` 是本專案自己的最小測試執行檔，停在其進
  入點、預設文字模式下，並不是客戶自己的 Mode X 遊戲——設計文件驗收計畫
  裡「真正 Mode X 重繪前後畫面是否一致」這一項，仍需要直接對著那款遊戲
  才能驗證。

---

## New capability — `io.write`, whitelisted VGA I/O port writes (2026-09-17)

**English**

- Added `io.write` to the native AI bridge (`debug_ai.cpp`) and a
  matching `write_io_port` MCP tool, so an agent can write directly to
  VGA I/O ports while stopped at a breakpoint -- something no existing
  bridge method could do, since `memory.write` only reaches guest RAM,
  never I/O space. This closes a concrete gap raised during debugging: an
  agent stopped at a breakpoint had no way to safely switch the VGA read
  plane, because doing so requires writing the Graphics Controller's
  Read Map Select register (I/O port `3CE`/`3CF`), not guest memory.
- Scoped to a deliberate allowlist (`WRITABLE_IO_PORTS`, debug_ai.cpp)
  rather than an unrestricted port write: only the standard VGA
  CRTC/Sequencer/Graphics Controller/Attribute Controller/DAC/Misc
  Output/Feature Control ports are writable. An unrestricted `io.write`
  could reach PIC/PIT/disk-controller ports and desync or hang the guest
  OS in ways a debugger session has no way to recover from; any
  non-whitelisted port is rejected with a dedicated `PORT_NOT_WRITABLE`
  error code, mirroring how `register.write` (Phase 4A) already handles
  `REGISTER_NOT_WRITABLE`. See "I/O port write safety" in
  `docs/dosbox-ai-bridge.md` for the full port list and rationale.
- Verified against a live, running `dosbox-x.exe` (rebuilt
  `dosbox-x.vcxproj`, 0 errors): a non-whitelisted port (`0060`, the
  keyboard controller) is correctly rejected before it ever reaches
  `IO_WriteB()`; both 1-byte and 2-byte (combined index+data) writes
  succeed. The motivating read-plane scenario itself was verified against
  genuinely live VGA hardware state, not just a protocol-level echo:
  `write_io_port()` selected write plane 0 via the Sequencer's Map Mask
  register and wrote `AA` to `A000:0000`, then selected write plane 2 the
  same way and wrote `55` to the same address; switching the *read*
  plane via the Graphics Controller's Read Map Select register and
  reading `A000:0000` back returned `AA` on plane 0, `55` on plane 2, and
  the pre-existing bytes on the untouched planes 1/3 -- the same one CPU
  address genuinely resolving to four independent bytes depending only on
  which plane had most recently been selected through `io.write`.

**繁體中文**

- 在原生 AI bridge（`debug_ai.cpp`）新增 `io.write`，並對應加上
  `write_io_port` 這個 MCP 工具，讓 agent 能在 breakpoint 停住時直接寫
  VGA I/O port——這是現有 bridge 方法都做不到的，因為 `memory.write`
  只能碰到 guest RAM，碰不到 I/O space。這解決了除錯過程中發現的一個具
  體缺口：agent 停在 breakpoint 時沒辦法安全切換 VGA read plane，因為
  要做到這件事必須寫 Graphics Controller 的 Read Map Select 暫存器
  （I/O port `3CE`/`3CF`），而不是寫 guest 記憶體。
- 刻意限縮在白名單（`WRITABLE_IO_PORTS`，debug_ai.cpp）內，而不是開放
  任意 port 寫入：只有標準 VGA CRTC／Sequencer／Graphics Controller／
  Attribute Controller／DAC／Misc Output／Feature Control 的 port 可寫。
  不受限的 `io.write` 有可能寫到 PIC／PIT／磁碟控制器等 port，讓 guest
  OS 失步或當掉，而且除錯 session 完全沒辦法救回來；任何不在白名單內的
  port 一律以專屬的 `PORT_NOT_WRITABLE` 錯誤碼拒絕，做法比照
  `register.write`（Phase 4A）既有的 `REGISTER_NOT_WRITABLE`。完整的
  port 清單與理由見 `docs/dosbox-ai-bridge.md` 的「I/O port write
  safety」一節。
- 已對著真正在跑的 `dosbox-x.exe` 驗證（重建 `dosbox-x.vcxproj`，0 錯
  誤）：寫不在白名單內的 port（`0060`，鍵盤控制器）會在碰到
  `IO_WriteB()` 之前就被正確拒絕；1 byte 與 2 byte（index+data 合併寫
  入）都能成功。而最初促成這個功能的 read plane 情境，也是對著真正的
  VGA 硬體狀態驗證，不只是協定層的 echo：`write_io_port()` 先透過
  Sequencer 的 Map Mask 暫存器選到 write plane 0，寫入 `AA` 到
  `A000:0000`；再用同樣方式選到 write plane 2，把 `55` 寫到同一個位址；
  接著透過 Graphics Controller 的 Read Map Select 暫存器切換 *read*
  plane 後讀回 `A000:0000`，plane 0 讀到 `AA`、plane 2 讀到 `55`，未
  動過的 plane 1/3 則維持原本的內容——同一個 CPU 位址，確實會依照
  `io.write` 最後選到的 plane 而解析出四種不同的獨立位元組。

---

## Bridge fix — `-defaultdir` swallowing the next command-line switch (2026-08-17)

**English**

- Root-caused the actual remaining source of `-break-start`
  "unreliability" flagged as a known limitation in the Phase 7D and 7E
  design docs (and left unresolved after the console-crash fix below):
  `-defaultdir`'s option handler (`src/gui/sdlmain.cpp`,
  `DOSBOX_parse_argv()`) takes an *optional* path argument, but called
  `CommandLine::NextOptArgv()` unconditionally to try to get it.
  `NextOptArgv()` has no concept of "optional" -- it hands back
  whatever token comes next, even if that token is actually the
  following `-switch`. A bare `-defaultdir` (no path of its own)
  immediately followed by another option -- exactly the
  `-defaultdir -break-start <program>` form used throughout this
  project's own launch instructions and prior testing -- silently ate
  `-break-start` as a bogus (nonexistent) directory name, so
  `control->opt_break_start` was never set and the debugger never
  stopped. This is 100% reproducible for a fixed command line, not a
  race, which is why some sessions' test runs "worked" and others
  didn't: it depended entirely on whether `-defaultdir` happened to be
  given an explicit path in that particular invocation.
- Confirmed live via temporary diagnostic counters exposed through
  `debug.status`, which showed `DEBUG_EnableDebugger()` was never even
  called, and a raw log of every option token `GetOpt()` yielded, which
  showed `-defaultdir`'s handler consuming the literal string
  `-break-start` as its own argument.
- Fixed by peeking the next token (`CommandLine::GetCurrentArgv()`,
  which does not consume it) before calling `NextOptArgv()`, and only
  treating it as `-defaultdir`'s own argument if it doesn't itself look
  like another option (doesn't start with `-` or `/`) -- otherwise
  falling through to the existing "no argument given" path
  (`usecfgdir = true`), exactly as if `-defaultdir` had been the last
  token on the command line.
- Verified live: `-defaultdir -break-start drive_c\SPIN.COM` (the bare
  form, previously broken) and `-defaultdir <path> -break-start
  drive_c\SPIN.COM` (explicit path) both now correctly stop the
  debugger at the BIOS reset vector (`F000:FFF0`) before POST, as
  designed. `-break-start` itself was never unreliable.

**繁體中文**

- 追查出 Phase 7D／7E 設計文件中列為已知限制、在上面「除錯器主控台
  當機」修法之後仍未解決的 `-break-start`「不可靠」問題的真正根本原因：
  `-defaultdir` 的選項處理常式（`src/gui/sdlmain.cpp` 的
  `DOSBOX_parse_argv()`）本應接受一個**可省略**的路徑參數，卻無條件呼叫
  `CommandLine::NextOptArgv()` 去取它。`NextOptArgv()` 沒有「可省略」的
  概念——不管下一個 token 是不是其實是另一個 `-switch`，都會原封不動交
  出來。當裸的 `-defaultdir`（自己沒帶路徑）緊接著另一個選項——正是本
  專案自己的啟動說明和先前測試全程使用的
  `-defaultdir -break-start <程式>` 這種寫法——就會把 `-break-start`
  當成一個假的（根本不存在的）目錄名稱悄悄吃掉，導致
  `control->opt_break_start` 永遠不會被設成 `true`，除錯器也就永遠不會
  真的停下來。這是固定命令列下 100% 可重現的結果，不是競態條件——之所以
  有些 session 測試「成功」、有些「失敗」，純粹取決於那次呼叫的
  `-defaultdir` 有沒有剛好帶了明確路徑而已。
- 已透過暫時透過 `debug.status` 曝露的診斷計數器即時確認：
  `DEBUG_EnableDebugger()` 根本從未被呼叫過；另外也記錄了 `GetOpt()`
  依序解析出的每一個選項 token，直接看到 `-defaultdir` 的處理常式把
  `-break-start` 這個字串原封不動當成自己的參數吃掉。
- 修法：在呼叫 `NextOptArgv()` 之前，先用不會消耗 token 的
  `CommandLine::GetCurrentArgv()` 偷看一下下一個 token，只有在它看起來
  不像另一個選項（不是以 `-` 或 `/` 開頭）時，才真的把它當成
  `-defaultdir` 自己的參數；否則就走原本「沒有給參數」的既有路徑
  （`usecfgdir = true`），效果等同於 `-defaultdir` 剛好是命令列上最後一個
  token。
- 已即時驗證：`-defaultdir -break-start drive_c\SPIN.COM`（裸形式，先前
  會壞掉）以及 `-defaultdir <路徑> -break-start drive_c\SPIN.COM`（明確
  路徑）現在都能正確在 POST 之前，於 BIOS 重置向量（`F000:FFF0`）讓除
  錯器停下，符合原始設計。`-break-start` 本身其實從頭到尾都很可靠。

---

## Phase 7E — DOS file I/O high-level event log (2026-08-18)

**English**

- Added `configure_dos_io_log`/`list_dos_io_events`/`clear_dos_io_log`.
  While enabled, every completed real-mode `INT 21h`
  `open`(3Dh)/`close`(3Eh)/`read`(3Fh)/`write`(40h)/`seek`(42h) call is
  recorded with its real post-call result -- actual bytes transferred,
  `AX`, carry, DOS error code -- never merely the request. Five
  one-line hooks inside the existing `DOS_21Handler()` (`src/dos/dos.cpp`),
  each at the point that service has already computed its real result.
- `path_host` resolves via `localDrive::GetHostName()` -- DOSBox-X's own
  existing DOS-path-to-host-path conversion -- and is only ever
  populated for a real mounted host directory, `null` for image-mounted/
  ISO/network drives. `buffer.linear` (the real-mode `DS:DX` transfer
  buffer's linear address) lets an agent correlate a `read` with a
  later memory watchpoint on that same address -- composes directly
  with the existing Dark Sun case study workflow.
- Unlike every other dual-route (stopped vs. running) method elsewhere
  in this bridge, all three `dos.io.*` methods -- including
  `.configure` -- are answered directly under one plain mutex: DOS file
  I/O is comparatively rare (nowhere near Phase 7D's per-instruction
  rate), so no lock-free per-instruction design is needed here.
- **A real result-fabrication bug was found and fixed during live
  verification, not merely theorized**: the first working version read
  the carry flag from the live `reg_flags` global, which silently
  reported `carry: false` for every event -- including a
  guaranteed-failing open. Root cause: `CALLBACK_SCF()`
  (`src/cpu/callback.cpp`) patches the FLAGS word already saved on the
  stack for the pending IRET-equivalent return, never the live
  `reg_flags` -- fixed by reading that same stacked location. Caught
  only because verification specifically exercised a call known to
  fail, not just the success path -- see the design doc for the full
  root-cause writeup.
- Wired into `DOSBoxClient`/`ai/server.py` (bringing the tool count to
  37) and `AGENT_GUIDE.md`/`.zh-TW.md`, including a documented known
  limitation: many DOS shell built-ins (e.g. `TYPE`) use an older
  FCB-based file access path that this log does not see at all, by
  design (out of this phase's declared scope) -- confirmed live (zero
  events from `TYPE` against a real file) rather than assumed.
- Verified live end-to-end (raw protocol and the actual MCP tool
  functions) against a purpose-built real-mode test program: Open ->
  Lseek -> Read (16 bytes) -> Close produced four correct events in
  order (path, handle, offsets, byte counts, buffer, AX all verified
  self-consistent); a guaranteed failed open correctly reported
  `carry: true`, `dos_error: 2` (File Not Found); `path_globs:
  ["*.GFF"]` against unrelated `*.DAT` I/O produced zero events, not
  merely hidden ones.
- See `docs/phase7e-dos-io-event-log-design.md` for the full design,
  source investigation, and verification notes.

This completes all five epics (A-E) of the Phase 7 requirements draft.

**繁體中文**

- 新增 `configure_dos_io_log`／`list_dos_io_events`／`clear_dos_io_log`。
  啟用期間，每一次完成的 real-mode `INT 21h`
  `open`(3Dh)／`close`(3Eh)／`read`(3Fh)／`write`(40h)／`seek`(42h)
  呼叫都會被記錄下來，附上真實的呼叫後結果——實際傳輸的位元組數、
  `AX`、carry、DOS 錯誤碼——絕不只是請求本身。在既有的 `DOS_21Handler()`
  （`src/dos/dos.cpp`）裡加了五個各一行的掛鉤點，各自插在該服務已經
  算出真實結果的那個時間點。
- `path_host` 是透過 `localDrive::GetHostName()`——DOSBox-X 自己既有的
  DOS 路徑轉主機路徑機制——來解析的，只有真正掛載到主機目錄的磁碟才會
  有值，image 掛載／ISO／網路磁碟一律是 `null`。`buffer.linear`（呼叫者
  傳入的 real-mode `DS:DX` 傳輸緩衝區的線性位址）讓 agent 可以把一次
  `read` 跟之後設在同一個位址的記憶體監看點對照——可以直接跟既有的
  Dark Sun 案例研究工作流程組合使用。
- 跟這個橋接層裡其他所有雙路由（停止／執行中）方法不同，所有三個
  `dos.io.*` 方法——包括 `.configure`——都是在同一個普通 mutex 下直接
  回答的：DOS 檔案 I/O 相對少見（完全不到 Phase 7D 那種逐指令頻率的
  等級），這裡不需要無鎖的逐指令設計。
- **這次實機驗證過程中真的找到並修正了一個「結果造假」的 bug，不只是
  理論上的擔心**：第一版能動的實作是從即時的 `reg_flags` 全域變數讀取
  carry 旗標，結果每一筆事件都悄悄回報 `carry: false`——包括一次保證
  會失敗的 open。根本原因：`CALLBACK_SCF()`（`src/cpu/callback.cpp`）
  修改的是已經存在堆疊上、等著被pending 的 IRET 等效返回讀走的那份
  FLAGS 字組，而不是即時的 `reg_flags`——修法是改讀同一個堆疊位置。
  這個 bug 只有在驗證時特意測了一次「保證失敗」的呼叫才被抓到，不是只
  測成功路徑——完整根本原因分析見設計文件。
- 已接上 `DOSBoxClient`／`ai/server.py`（工具數來到 37 個）與
  `AGENT_GUIDE.md`／`.zh-TW.md`，並記錄了一個已知限制：很多 DOS shell
  內建指令（例如 `TYPE`）內部用的是比較舊的 FCB 式檔案存取路徑，這個
  記錄機制完全看不到——這是本 phase 宣告範圍之外，設計上本來就如此
  ——已實機確認（對一個真實存在的檔案跑 `TYPE`，產生零筆事件），不是
  憑假設。
- 已完整實機端對端驗證（原始協定與實際 MCP 工具函式）：針對一個特別
  寫的 real-mode 測試程式，Open → Lseek → Read（16 bytes）→ Close
  依序產生四筆正確事件（路徑、handle、offset、位元組數、buffer、AX
  互相對照都一致）；一次保證失敗的 open 正確回報 `carry: true`、
  `dos_error: 2`（File Not Found）；`path_globs: ["*.GFF"]` 對不相關的
  `*.DAT` I/O 產生零筆事件，不只是被藏起來。
- 完整設計、原始碼調查與驗證細節見
  `docs/phase7e-dos-io-event-log-design.md`。

這次完成了 Phase 7 需求草案的全部五個 Epic（A-E）。

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
