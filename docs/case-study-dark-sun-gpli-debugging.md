# 案例集：用 DOSBox-X-AI 追查 Dark Sun 劇情觸發與對話失效

> 日期：2026-08-16  
> 遊戲：*Dark Sun: Shattered Lands*（DOS）  
> 對象：需要除錯舊 DOS 遊戲、工具或資料檔的後續使用者  
> 相關設計：`docs/phase6b-input-injection-design.md`、
> `docs/phase7-observability-and-autonomous-control-requirements.md`

## 摘要

本案例的目標是把一個看起來像「繁中翻譯讓遊戲劇情壞掉」的問題，縮小成可重現、可驗證的
資料位址相容性問題。

最終結果有兩個：

1. 出口觸發失效是 GPL-3 的既有外部入口位址未保持相容所致。
2. 鬥獸場受綁囚犯的 Talk 無反應，是 `GPLDATA.GFF/GPLI-1` 的間接事件表仍保存舊 GPL-5
   offset 所致；不是 UI、翻譯文字、存檔本身或地圖碰撞資料的問題。

第一項主要依賴靜態 GPL 位址／入口分析；第二項則是 DOSBox-X-AI 的 real-mode memory
watchpoint 讓調查從大量猜測變成直接資料流證據的例子。

以下每個「差距」都是工程成本的質性比較，不是通用效能基準；實際差距取決於程式是否有
符號、資料格式是否已知、是否能重複觸發，以及是否有願意協助操作的測試者。

## 共通環境與工具

| 類型 | 工具／方法 | 在本案例的角色 |
|---|---|---|
| 客體動態除錯 | DOSBox-X-AI bridge（localhost:9876） | 暫停／繼續、設定中斷點／memory watchpoint、讀 RAM、讀 CPU、反組譯 |
| 客體操作 | Phase 6B input injection | 嘗試送按鍵、相對滑鼠事件；本案也暴露 capture 與絕對座標的限制 |
| 靜態資料 | GFF extraction、hex search、GPL disassembler | 找到 chunk、比對舊／新 offset、確認 instruction boundary |
| 轉換建置 | `compile_gpl_dialogue_patch.py`、`build_cjk_display_staging.py` | 產生可重現的 GPL／GPLI 重定位與 staging build |
| 實機驗證 | 人類測試者操作 DOSBox-X | 驗證 Talk、出口 Yes/No、轉場、戰鬥與中文行距 |

### 動態除錯的基本守則

1. 先以 `get_debug_status()` 判斷客體是否停止。
2. **停止時**才讀記憶體、CPU、反組譯、調整 breakpoint。
3. **執行時**才用 `input.*` 送輸入；bridge 對 stopped guest 應回傳 `DEBUGGER_STOPPED`。
4. 每個實驗只保留必要 breakpoint；結束後列出並刪除，避免「隨便點一下都停住」污染後續測試。
5. 先記下遊戲進度、存檔、角色位置和預期事件；同一張地圖的事件常受劇情旗標影響。

Python 最小連線範例：

```python
import sys
sys.path.insert(0, r"D:\git\DOSBox-X-AI\ai")
from dosbox_client import DOSBoxClient

c = DOSBoxClient("127.0.0.1", 9876)
print(c.get_debug_status())
```

## 案例 1：出口走到門前沒有 Yes/No 對話

### 症狀與初始假設

翻譯版中，角色可以走到出口前，但不出現「是否離開」對話；英文版在相同劇情進度與位置會
出現。初始合理假設包括：ETAB 地圖觸發資料包含舊位址、GPL 內部 branch 重定位漏修、或
劇情旗標／區域資料讓出口被鎖住。

### 實際根因

GPL 對話 chunk 改成可變長後，GPL-3 有一個會被外部資料／程式進入的既有入口。
一般「將所有 local branch 依新 offset 重定位」不足夠；該入口也必須保留在原 offset。
否則地圖事件仍跳到舊位置，卻開始解讀到不同指令。

### 用到的工具與操作方式

1. **英文／中文 A/B 實機流程**：以相同存檔走到同一出口，先確認差異是可重現的，而非
   玩家位置、未完成對話或錯誤劇情階段。
2. **GPL 靜態反組譯**：列出 GPL-3 的 instruction boundary、branch target 與原始入口。
   將「入口」和「只供本 chunk 的 local target」區分開來。
3. **建置器 invariant**：在 `compile_gpl_dialogue_patch.py` 加入
   `--preserve-external-entries` 類型的契約：固定入口不再是偶然保留，而是每次編譯都驗證。
4. **DOSBox-X-AI 交叉驗證**：在出口即將觸發時用 code breakpoint／CPU state 確認執行流
   確實進入該 GPL 路徑，而不是地圖座標或滑鼠點擊根本沒到事件入口。
5. **人工回歸**：驗證 Yes/No、選 No 後仍停在出口前、選 Yes 後轉場、以及緊接的戰鬥流程。

### 沒有 DOSBox-X-AI 時的替代方式

- 靜態比對原版與翻譯版 GPL bytes，猜測所有「看起來像 offset」的 word 是否需要修正。
- 對每個猜測建立一版 patch，啟動遊戲、重走劇情、請人測出口。
- 將條件旗標、ETAB、GMAP、RMAP、存檔差異全部輪流排除。

這仍可成功，因為固定入口的問題可從嚴謹的靜態 ABI 設計找出；但無法快速證明「遊戲真的
走到哪一個入口」。容易把未觸發、走錯劇情階段與跳到錯位址混成同一類症狀。

### 差距

| 面向 | 有 bridge | 沒有 bridge |
|---|---|---|
| 執行流證據 | 可在實際觸發點讀 `CS:IP`／暫存器 | 只能從結果反推 |
| 假設淘汰 | 可先排除「事件根本未進 GPL」 | 常需做 patch 才知道 |
| 人工測試成本 | 用於最後回歸 | 幾乎每個假設都要重跑 |
| 典型風險 | breakpoint 設太廣導致干擾遊戲 | 多版本試誤造成因果不清 |

## 案例 2：囚犯 GUI 有 Talk，但按下後完全無反應

### 症狀與初始誤導

鬥獸場的受綁囚犯可被選取，有些會顯示 GUI 與 `TALK`。英文版可進對話；翻譯版按下後無
反應。先前已經修過 GPL-5 中兩個 `talktotrigger` 的嵌入 literal：

```text
GPL-5 0x092C -> 0x093E
GPL-5 0x1982 -> 0x195D
```

靜態 script 已經正確，卻沒有改變遊戲行為。這是本案最重要的「靜態修好但 runtime 仍錯」
場景。

### 關鍵觀察與根因

客體 RAM 的 runtime trigger table 仍有舊值：

```text
event 0x18 -> GPL-5@0x092C
event 0x1A -> GPL-5@0x1982
```

在 table 的 target word 設 real-mode write watchpoint 後，首次命中只是 DOS `INT 21h/AH=3F`
讀檔；第二次命中落在真實遊戲程式 `5B7C:1D04..1D68`。反組譯與記憶體 read-back 顯示它在
載入時讀取一份 6-byte map，格式是：

```text
event_id:u16le, gpl_offset:u16le, gpl_chunk:u16le
```

再對檔案做 hex search，唯一含有兩個 pair 的來源是 `GPLDATA.GFF/GPLI-1`。其中：

```text
18 00 2C 09 05 00  # event 0x18 -> GPL-5@0x092C
1A 00 82 19 05 00  # event 0x1A -> GPL-5@0x1982
```

所以真正漏修的是 GPLI-1 的**間接事件表**；每次存檔／區域載入，它都會把舊 offset 寫回
runtime trigger table，覆蓋已修好的 GPL literal。

### 用到的工具與操作方式

1. **靜態 A/B 資料比較**：確認已修 GPL-5 instruction 中的 literal 正確，建立「問題不在
   該 literal」的基線。
2. **RAM read-back**：在 Talk 事件對應的 runtime table 讀取 bytes，發現舊 offset 仍存在。
3. **real-mode memory write watchpoint**：監看 target word；使用者進行 `SAVE05` load 或靠近
   囚犯等最小可重現操作，命中後停止。
4. **CPU／反組譯**：讀命中時的 `CS:IP`、暫存器與周邊指令，區分「DOS 讀取」與「遊戲的
   6-byte record 搬運迴圈」。
5. **檔案 hex search**：搜尋 `{event, old_offset, chunk}` 的 little-endian bytes，定位 GPLI-1。
6. **安全的資料修補**：編譯器建立 original→patched instruction-boundary offset map；只有當
   GPLI record 的 chunk 被重建且 old target 是已知原 instruction boundary 時才重定位。這避免
   將任意看似 word 的資料誤改。
7. **runtime 重新驗證**：重新載入存檔後確認 runtime table 變為 `0x093E`／`0x195D`；最後由
   測試者驗證兩名囚犯均可對話。

### 沒有 DOSBox-X-AI 時的替代方式

可行，但明顯更迂迴：

1. 列舉所有 GFF chunk，搜尋舊 offset byte pattern。
2. 對每個候選 table 做 patch，建立多個 A/B 版本。
3. 每一版都要載入存檔、走到囚犯、開 GUI、按 Talk。
4. 若失敗，仍不知道候選資料是否根本未被載入、載入後被覆蓋，或新 offset 本身不對。

另一種是使用傳統 DOS debugger／DOSBox 內建 debugger 手動設 watchpoint、抄下暫存器、
自行反組譯。這在技術上等價，但缺少結構化 API、可重複腳本化的 memory read、穩定的
breakpoint 管理與機器可讀結果。

### 差距

| 面向 | 有 bridge | 沒有 bridge |
|---|---|---|
| 根因定位 | 直接看到「誰把舊值寫回 RAM」 | 只能猜哪份檔案間接載入 |
| 格式發現 | write site 的步長與來源 bytes 指向 6-byte record | 必須從所有資料檔模式自行聚類 |
| 修補安全性 | 以 runtime 資料流驗證，再用 instruction map 限縮修補 | 容易廣泛替換而傷及非程式資料 |
| 調查迭代 | 少量、明確的停點與 read-back | 大量 patch-build-play 迴圈 |
| 可移植性 | 方法可套用到其他「載入後覆寫」問題 | 結果常只解決這一個事件 |

## 案例 3：功能全修好後，中文行距又退回錯誤狀態

### 症狀

v25 已修好囚犯 Talk、出口與戰鬥，但對話文字行距比 v15 緊，造成可讀性回歸。這不是 runtime
事件觸發失效，而是 build parameter 漏帶造成的視覺回歸。

### 用到的工具與操作方式

1. **build manifest 比對**：對照 v15 和 v25 的 `build-manifest.json`：

```text
v15: ebox_layout_line_gap = 2, ebox_next_page_delta = -3
v25: ebox_layout_line_gap = 0, ebox_next_page_delta = -5
```

2. **檢查建置器預設值**：找到 `build_cjk_display_staging.py` 的預設 line gap 為 0；v25 指令
   沒有顯式傳入 `--ebox-line-gap 2`。
3. **建立 v26**：沿用已驗證的 GPLI 修補 package，顯式加入 `--ebox-line-gap 2`。
4. **實機畫面驗證**：由使用者確認中文兩行之間的空隙恢復，並再次確認囚犯、出口、轉場、
   戰鬥未回歸。

### 沒有 DOSBox-X-AI 時的替代方式

本案例幾乎不需要動態除錯。manifest 與畫面 A/B 就足夠；即使沒有 bridge 也能高效率完成。
bridge 的價值在於把「視覺修補後需重跑哪些功能」的回歸流程接到同一個可觀測環境，而非
發現 line gap 根因本身。

### 差距

| 面向 | 有 manifest／可重現建置 | 只有人工改檔與截圖 |
|---|---|---|
| 根因 | 可直接比對建置參數 | 容易誤判為字型、renderer 或文字內容問題 |
| 修復 | 單一顯式參數、可重建 | 容易再產生無法重現的「手調版本」 |
| 驗證 | 雜湊與功能回歸一起記錄 | 常只留下視覺印象 |

## 案例 4：agent 嘗試自行操作遊戲，暴露現有輸入能力邊界

### 目標與結果

為了載入測試存檔並自行走到驗證點，嘗試使用 Phase 6B 的 `key_tap`、`click_mouse` 與
`move_mouse_relative`。bridge 能確認請求成功送入內部輸入入口，但主選單未可靠地響應；
後來改由使用者接手，並以 DOSBox-X capture 操作完成測試。

這不是 Phase 6B 無效：它仍適合「客體已在已知 input loop、已捕捉滑鼠或只需按 Enter 推進
對話」的除錯場景。問題在於主選單需要穩定的 mouse capture、絕對位置和可見畫面，現有
API 沒有提供這三者。

### 實際學到的限制

- `input.mouse.move_relative` 的文件契約是：只有 DOSBox-X 已 capture，且客體讀取相對滑鼠
  時才有效；方法本身不切換 capture。
- `input.*` 的 `{tapped:true}`／`{clicked:true}` 只表示 bridge 成功 dispatch，不表示遊戲 UI
  已採用輸入。
- bridge 沒有 framebuffer capture，因此為了看畫面而採用主機桌面截圖會受 DPI、視窗位置、
  遮蔽與其他使用者視窗干擾。
- 對真實遊戲 UI，只有相對位移而沒有 `click_at(x,y)`，會使 agent 無法可靠重現一次操作。

### 本案的正確替代策略

- 需要立即完成遊戲回歸時：由使用者操作，agent 只在明確的停止點進行讀取／除錯。
- 需要全自動流程時：先實作 Phase 7 的 framebuffer、capture get/set、絕對點擊與 receipt，
  再嘗試 UI 自動化。
- 不建議把 OS-level window focus／SendKeys／桌面滑鼠注入當成 bridge 的正式替代品；它依賴
  主機桌面狀態，也違反 Phase 6B 對客體內部輸入路徑的設計界線。

### 差距與後續需求的對應

| 缺口 | 本案後果 | Phase 7 對應 |
|---|---|---|
| 無直接 frame | agent 看不到可靠客體狀態 | Epic A |
| 無 capture state | 不知道 relative motion 是否有效 | Epic B |
| 無 absolute click | 無法選定 UI 上的確切目標 | Epic B |
| 僅有 dispatch 回應 | 無法分辨遊戲忽略輸入或位置不對 | Epic C + screenshot／watchpoint |

## 可複用的調查決策樹

```text
可重現的英文／翻譯版差異？
  └─ 否：先固定存檔、劇情旗標、位置、輸入方式
  └─ 是：靜態比對修改過的資料與原版
       ├─ 靜態資料已正確，但 runtime 仍錯？
       │    └─ 讀 runtime buffer；對舊值設 write watchpoint
       │         └─ 命中後讀 CS:IP、暫存器、附近指令與來源 bytes
       │              └─ 找到 loader／間接表，再建立狹義重定位規則
       ├─ 入口／callback 被外部引用？
       │    └─ 將其列為 ABI，編譯時 preserve + verify
       └─ 只是視覺／layout 回歸？
            └─ 先比 manifest／顯式建置參數，再做少量 UI 回歸
```

## 後續使用者的最小工作清單

1. 建立「原版對照、問題版、候選修補版」三份可重現 staging，不在原始遊戲目錄直接修改。
2. 對每個觀察寫下觸發條件：存檔、地圖、座標／NPC、前置對話、預期畫面。
3. 問題若是「資料已改但行為未變」，優先查 runtime 是否被另一個載入表覆寫。
4. 監看點命中時，先保存狀態，再繼續遊戲；不要邊改 breakpoint 邊讓玩家盲測。
5. 將修補限制在已證明的 record／instruction boundary，並為每個不變性加入自動測試。
6. 功能修好後，以 manifest、雜湊與實機回歸一併記錄，才升格 checkpoint。

## 結論

DOSBox-X-AI 在這次工作中最大的價值，不是取代人類玩遊戲，而是把「遊戲黑箱中的一個無反應
按鈕」轉為可追蹤的 runtime 寫入、真實執行位置與可驗證的資料格式。沒有 bridge 仍能藉由
靜態分析與反覆 A/B patch 完成，但調查會更仰賴猜測、需要更多人工重跑，也較難建立可套用到
下一個事件系統問題的方法。
