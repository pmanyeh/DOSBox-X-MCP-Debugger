可以繼續。

目前 Phase 4E 仍維持 BLOCKED。

第一個 `0xC0000409` blocker 已經由 minidump + PDB 確認 root cause 並以最小修復處理；這部分暫時接受。

現在只處理第二個 blocker：

`dosbox-x.exe -break-start`
→ 不再 crash
→ 約 3 秒後乾淨退出
→ ExitCode = 8
→ 無 dump
→ 無 Event Viewer Application Error

## 目標

只找出 ExitCode 8 的 root cause。

不要開始 Phase 4E functional acceptance。

不要開始 Phase 5。

不要修改 MCP、Python、Native Bridge protocol 或 debugger architecture。

---

## 1. 先建立最小 reproduction

重複：

`dosbox-x.exe -break-start`

確認：

* ExitCode
* elapsed time
* stdout/stderr（若有）
* DOSBox-X log/output
* 是否有任何 debugger-related message
* 是否有新的 Windows event
* 是否有 crash dump

至少重現 2–3 次。

---

## 2. 找 ExitCode 8 的來源

不要先假設 exit code 8 是什麼意思。

在目前 DOSBox-X source 中搜尋：

* `exit(8)`
* `return 8`
* `EXIT_FAILURE` 等可能相關路徑
* DOSBox-X 自己的 exit-code enum/constant
* 所有 debugger startup / shutdown error paths

建立：

`-break-start → ... → ExitCode 8`

的實際 call path。

如果 ExitCode 8 是由某個 subsystem / exception / configuration failure 產生，請明確指出來源。

---

## 3. 特別比較正常啟動與 -break-start

建立最小差異：

### Normal

`dosbox-x.exe`

### Debugger startup

`dosbox-x.exe -break-start`

找出兩條 execution path 在退出前第一次出現的 divergence。

不要只檢查 `DEBUG_EnableDebugger()`。

也檢查：

* debugger UI initialization
* debugger loop
* DEBUG_Loop
* DEBUG_CheckKeys
* DEBUG_DrawScreen
* DEBUG_AI_Poll
* debugger window/control state
* emulator main loop
* shutdown path
* AddExitFunction callbacks
* thread lifetime
* SDL/window lifecycle

---

## 4. Use native diagnostics

優先使用 source-level/native diagnostics：

* debugger breakpoint
* call stack
* source tracing
* existing logging
* minidump only if an actual exception occurs

不要使用 GUI automation。

不要用 synthetic keyboard/mouse input。

---

## 5. 特別檢查 ExitCode 8 是否其實是正常的「requested exit」

如果 ExitCode 8 是由某個明確的 shutdown request 產生，確認：

* 誰設定了 shutdown/quit flag
* 誰呼叫了退出路徑
* 為什麼 `-break-start` 會觸發它
* normal startup 為什麼不會觸發

不要把「乾淨退出」誤認成「正常」。

Phase 4E 要求 debugger session 必須持續存在，因此目前 ExitCode 8 仍然是 blocker。

---

## 6. 檢查 Phase 3–4D 修改是否相關

可以分析：

* `debug_ai.cpp`
* `debug_ai.h`
* `debug.cpp`
* `dosbox.cpp`
* `include/debug.h`

但不要假設是 Phase 4D。

尤其確認：

* `DEBUG_AI_Init`
* `DEBUG_AI_Poll`
* `DEBUG_AI_ShutDown`
* `g_acceptThread`
* `AddExitFunction`
* debugger startup state
* main loop / shutdown interaction

---

## 7. 不要先修

找到 root cause 後：

STOP。

只回報：

### A. Exact reproduction

### B. ExitCode 8 source

### C. Call path

### D. Root cause

### E. Evidence

### F. Whether it is a Phase 3/4 regression

### G. Minimal proposed fix

### H. Files that would need modification

### I. Expected verification after fix

不要自行實作第二個修復，除非 root cause 是極其明確且修改只有一個非常小、無架構影響的 change；即使如此，也請先列出 proposed fix，再等待 Technical Architect approval。

---

## 8. Current status must remain

Phase 4E: BLOCKED

Phase 5: NOT STARTED

Do not report PASS.
