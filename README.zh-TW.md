# DOSBox-X MCP Debugger

*[English](README.md) | [繁體中文](README.zh-TW.md)*

一個實驗性的 MCP 整合專案，讓 AI agent 能透過受限、可稽核的工具介面，
檢視並控制原生的 DOSBox-X 除錯器。

本專案主要用於 DOS 程式除錯與逆向工程研究，包括調查早期遊戲的資料流，
例如執行期文字解碼、片語組合、指令碼執行與繪圖流程。

> [!IMPORTANT]
> 這是一個工程預覽版本。真正的 MCP 傳輸與強制執行層已經實作並經過測試，
> 但正式的 Phase 5C 自主 agent 驗收結果為 **未通過（NOT PASS）**：
> 4 個代表性 agent 場景中有 3 個通過。完整、未刪節的結果請見
> [`docs/phase5c-final-report.md`](docs/phase5c-final-report.md)。

## 為什麼要做這個專案

傳統的 AI 輔助除錯，通常需要一個人擔任手動中繼站：

1. AI 建議一個中斷點或除錯操作；
2. 由人在 GUI 中執行該操作；
3. 由人把暫存器、記憶體或反組譯結果複製回給 AI；
4. 整個流程一次只能處理一個指令，如此反覆。

DOSBox-X MCP Debugger 移除了這個中繼站。agent 可以使用原生的 MCP 工具，
觀察並控制與人類所見相同的 DOSBox-X 除錯器與客體 CPU，同時每個請求
仍然受到範圍限制且可追蹤。

## 架構

```mermaid
flowchart LR
    A["AI agent"] -->|MCP over stdio| B["受限的 MCP 伺服器"]
    B --> C["DOSBoxClient"]
    C -->|TCP on 127.0.0.1:9876| D["原生 AI 橋接層"]
    D --> E["DOSBox-X 除錯器與客體 CPU"]
```

本專案刻意**不**引入：

- GUI 自動化；
- 第二套 CPU 模擬器；
- 平行的中斷點實作；
- 虛構的除錯器狀態。

中斷點、單步執行、執行控制、暫存器讀取、記憶體讀取與反組譯，
都是由原生的 DOSBox-X 除錯器機制所支援。

## Agent 可見的工具

本章節說明的是專門用於受限的 Phase 5C 研究介面（供本專案自己的受控驗收
測試使用）。若要找一般 agent 應該連線、不受限的 34 個工具通用介面，
請見〈[AI Agent 使用說明](AGENT_GUIDE.zh-TW.md)〉。

目前受限的 Phase 5C 介面共暴露 12 個工具：

| 分類 | 工具 |
| --- | --- |
| 除錯器狀態 | `get_debug_status`、`get_cpu_state`、`get_current_instruction` |
| 檢視 | `read_memory`、`disassemble` |
| 中斷點 | `set_breakpoint`、`delete_breakpoint`、`list_breakpoints` |
| 執行控制 | `continue_execution`、`pause_execution`、`step_into`、`step_over` |

`get_cpu_state` 回傳的是暫存器快照，本身並不能證明執行已經停止。
需要「執行中／已停止」證據的 agent，必須呼叫 `get_debug_status`。

Phase 5C 面向 agent 的 MCP 伺服器，刻意**不**暴露暫存器與記憶體的
寫入能力。

## 受限工作階段（Bounded sessions）

每一個受限的除錯工作階段都擁有各自獨立的：

- 允許使用的工具政策；
- 呼叫總數預算；
- 執行操作預算；
- 單調遞增的看門狗（watchdog）截止時間；
- 終止狀態；
- 機器可讀的證據紀錄。

任何被拒絕的請求，必須在到達 `DOSBoxClient` 之前就被攔截，不得傳到
原生橋接層，也不得改變 DOSBox-X 的狀態。

## 目前專案狀態

### Phase 5C 結果

| 層級 | 結果 |
| --- | --- |
| C1 — 真實 MCP 連線 | **通過** |
| C2 — 傳輸層等效性 | **通過** |
| C3/C3-E — 透過真實 MCP 的受限強制執行 | **通過** |
| C4 — 全新自主 agent 除錯 | **未通過**（4 項組合證據中通過 3 項） |
| C5 — 回歸測試與凍結狀態驗證 | **通過** |

反覆出現的 C4 失敗範圍很小，但意義重大：兩個獨立的全新 agent
都完成了預期的「設中斷點／執行／讀暫存器」流程，但都以 `get_cpu_state`
作為最終觀察結果，沒有另外透過 `get_debug_status` 獨立確認執行確實
已經停止。

這項結果被完整保留，而非隱藏或重複執行到通過為止。此傳輸層實作
可用於受控的研究情境，但本專案並不宣稱已達到完整的自主 agent
可靠性。

### 結案時的回歸測試證據

- Phase 5C 確定性測試套件：**23/23 通過**
- Phase 5A 即時回歸測試：**16/16 通過**
- Phase 5B 回歸測試：**40/40 通過**
- 離線除錯器回歸測試：**17/17 通過**

實作檢查點對應的 commit 為
`8357b435c39d5ad2e589bc611ce15f868fa78cdf`。

## 預期工作流程

一次典型的逆向工程調查，預期會是這樣的流程：

1. 由人類在 DOS 程式或遊戲中重現目標事件。
2. Agent 檢視除錯器狀態並安裝候選中斷點。
3. 必要時由人類觸發該事件。
4. Agent 透過原生 MCP 工具追蹤執行流程、記憶體與反組譯結果。
5. 該工作階段會產生一份證據紀錄，區分「觀察結果」、「推論」與
   「尚未解決的問題」。

第一個計畫中的實際遊戲概念驗證（proof-of-value）試點，將調查
一行可重現的遊戲文字，在到達繪圖層之前是如何組成的：究竟是完整
字串、逐段附加的片語、token 串流，還是帶有執行期替換的樣板。

## 目錄結構

```text
ai/                  MCP 伺服器與 DOSBox client 整合
docs/                架構文件、各階段設計與驗收報告
tests/phase5a/       工具感知能力驗收基礎設施
tests/phase5b/       受限自主性驗收基礎設施
tests/phase5c/       真實 MCP 傳輸層與證據測試
dosbox-src/          DOSBox-X Native AI Bridge fork，以 git submodule 追蹤
```

## 快速上手

`dosbox-src` 是一個指向
[`pmanyeh/dosbox-x`](https://github.com/pmanyeh/dosbox-x) 的 git submodule，
分支為 `ai-mcp-bridge`，固定於 commit
`5fcf624b787e1017273b313de6f9a70f12422102`
（在未修改的上游 DOSBox-X 基礎上疊加 Native AI Bridge）。透過一次性的
乾淨 clone 已獨立驗證能正確 clone 並解析到該確切 commit（詳見
`docs/phase5c-final-report.md`）。

### Clone

> [!IMPORTANT]
> 在 Windows 上，上游 DOSBox-X 的歷史記錄中（`docs/PLANS/`、`ref/` 下）
> 包含一些過長的檔案路徑。若再加上巢狀很深的 clone 目的地路徑，
> `git submodule update --init` 可能會因為 `Filename too long` 而失敗。
> 在 clone 之前，請先執行一次：
>
> ```
> git config --global core.longpaths true
> ```
>
> 並將專案 clone 到較短的路徑（例如 `C:\dev\DOSBox-X-MCP-Debugger`），
> 而不要放在 `AppData`／`Temp` 等預設路徑深處。

```
git clone --recurse-submodules https://github.com/pmanyeh/DOSBox-X-MCP-Debugger.git
```

（若已經在未加 `--recurse-submodules` 的情況下 clone 過，可執行：
`git submodule update --init`。）

### Python 環境（已對照 `requirements.txt` 驗證）

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

這會安裝固定版本的 `mcp==2.0.0` SDK 以及 `pytest`。

### 建置原生橋接層（Native Bridge）

`dosbox-src` 的建置方式與上游 DOSBox-X 在 Windows 上的建置方式相同——
本專案更動的是原始碼，而非建置系統本身。請依照
[`dosbox-src/README.development-in-Windows`](https://github.com/pmanyeh/dosbox-x/blob/ai-mcp-bridge/README.development-in-Windows)
的說明進行（需要 Visual Studio 2019 以上，使用 `vs/dosbox-x.sln`
方案檔）。**在全新機器上從零建置，尚未在本次稽核中獨立重新驗證**——
本次工作階段實際驗證過的，是在既有已建置完成的執行檔上，對照目前的
橋接層原始碼執行測試（63/63 項原生橋接層通訊協定檢查全數通過，
以及完整的 Phase 5A/5B/5C 測試套件全數通過）。若在建置過程中遇到
任何問題，歡迎回報。

### 健康檢查（Health checks）

`bin/`（建置輸出目錄，含 `dosbox-x.conf`）不受 `dosbox-src` 追蹤——
它是由上述建置流程產生的。第一次啟動時，DOSBox-X 會提示一次要求
選擇工作目錄；請選擇專案根目錄，並可選擇儲存該設定，讓之後啟動時
不再詢問：

```
dosbox-src\bin\x64\Release\dosbox-x.exe -break-start drive_c\STEP.COM
.venv\Scripts\python.exe tests\test_native_bridge.py
```

應該會看到 63/63 項檢查通過。接著可以選擇性地執行更完整的測試套件：

```
.venv\Scripts\python.exe -m pytest tests\phase5c -q
.venv\Scripts\python.exe -m pytest tests\phase5b -q
.venv\Scripts\python.exe -m pytest tests\test_debugger.py -q
```

（`tests/phase5c` 與 `tests/phase5b` 中的即時測試案例，需要針對該場景
的目標程式（`STEP.COM` 或 `TEST.COM`）重新啟動一個全新的 DOSBox-X——
確切的啟動／定位輔助方式，請參考本專案自身測試所使用的
`tests/phase5c/scenario_setup.py`。）

### 清理

`scratchpad/` 目錄下的內容（僅限於本機工作階段：戰役追蹤紀錄、
產生的 MCP 設定檔、OAuth／預檢產出物、證據紀錄）並不打算保留或
提交進版本控制——隨時刪除都是安全的，而且該目錄已經被
`.gitignore` 排除。

## 安全性與隱私

- 原生橋接層只綁定到本機迴路位址（`127.0.0.1`），而非對外公開的
  網路介面。
- MCP 工具的可用範圍，是依每個受限工作階段個別控制的。
- 被拒絕的操作會被記錄下來，但不會被轉送出去。
- 憑證、OAuth 狀態、產生的 MCP 設定檔、本機追蹤紀錄、虛擬環境與
  建置產物，都不得提交進版本控制。
- 本儲存庫不包含任何商業遊戲的執行檔、遊戲資料、存檔、說明書、
  截圖或擷取出來的素材。

## 文件

- **[AI Agent 使用說明](AGENT_GUIDE.zh-TW.md)**——所需環境、安裝步驟、
  agent 可呼叫的每一個 MCP 工具、錯誤代碼，以及範例工作流程。若您要把
  agent 接上本專案，請從這裡開始。
- **[更新日誌](CHANGELOG.md)**——依開發階段整理的重要變更，中英文並呈。
- [Phase 5C 傳輸層設計](docs/phase5c-real-mcp-transport-design.md)
- [Phase 5C 最終報告](docs/phase5c-final-report.md)
- [Phase 5C 實作狀態檢查點](docs/phase5c-implemented-state-checkpoint.md)

## 專案範圍

本儲存庫提供的是通用的除錯器整合。特定遊戲的研究、翻譯、擷取資料
與修補檔，應該存放於獨立的儲存庫中，並透過專案層級的 MCP 設定，
連接到本工具使用。

## 授權與隸屬關係

`dosbox-src` submodule（`pmanyeh/dosbox-x`）是上游 DOSBox-X 的 fork，
其授權條款仍為上游原本的 **GNU General Public License v2**
（詳見 `dosbox-src/COPYING`）；Native AI Bridge 的變更部分，
延續與其擴充之檔案相同的 GPL-2.0 授權標頭與著作權標示，且未曾更動
任何上游授權條款或著作權聲明。

> [!IMPORTANT]
> **本儲存庫自身的原創程式碼（`ai/` 與 `tests/` 下的 Python MCP 伺服器、
> 受限工作階段機制與測試／驗收基礎設施）目前尚未選定授權條款。**
> 尚未新增任何授權檔案，也不應假設任何授權條款已經生效。在明確
> 選定授權條款之前，該原創程式碼預設適用著作權保留（保留作者的
> 所有權利）。這是一個真實存在、尚待決定的開放問題，而非疏漏——
> 在本次公開發布的過程中，刻意不對此進行臆測。

本專案為獨立專案，並非 DOSBox-X 的官方專案，也非任何 AI 模型或
服務供應商的官方產品。
