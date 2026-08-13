Phase 5A — Debugger Agent Tool Awareness 開始。

目前 Phase 1–4E 已正式 PASS，Infrastructure v1.0 已驗收。

Phase 5A 第一階段只做 design + test harness，暫不開放 write_register / write_memory。

請先閱讀目前 MCP debugger tool definitions、Phase 4E acceptance tests、既有 debugger documentation，設計 5 個 Tool Awareness scenarios：

current-state inspection
instruction identification
CALL step-into vs step-over reasoning
breakpoint investigation
running/stopped state awareness

每個 scenario 必須定義：

initial debugger state
user task
expected tool-selection behavior
allowed tools
prohibited tools
expected state transitions
evidence requirements
PASS/FAIL criteria

目前不要修改 DOSBox-X C++。

目前不要修改 debugger protocol。

目前不要實作 autonomous debugging loop。

目前不要開放 write_register/write_memory 給 Agent。

如果需要修改 Python MCP layer 來建立 Phase 5A test harness，先提出修改計畫與理由，不要直接大改。

最後回報一份 Phase 5A design proposal，等待 Technical Architect review 後才開始 implementation。