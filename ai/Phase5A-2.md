Phase 5A Implementation Review: APPROVED FOR REAL-AGENT ACCEPTANCE.

不要修改目前 implementation。

現在請使用真正的 AI Agent，連接 ai/server_phase5a.py，依序執行 Phase 5A 的 5 個 Tool Awareness scenarios。

不要把 expected tool sequence 告訴 Agent；Agent 必須從自然語言 task 自行選擇 tools。

每個 scenario 使用 fresh real DOSBox-X debugging session，開始前確認 debugger 已經真正 stopped。

使用目前的 grading engine 評估結果。

必須保留完整 agent tool trace，並分別報告：

tool selection
unnecessary tool calls
state transitions
final observed state
evidence
grading result

特別注意：

正確答案但使用不必要 debugger operation，仍 FAIL。
CALL scenario 必須以真實 CS:EIP state transition 判定。
Running/stopped scenario 必須證明 Agent 先理解目前 state，再決定是否 pause。
不得使用 write_register / write_memory。
不得修改 DOSBox-X C++、Native Bridge、production ai/server.py。
不要開始 autonomous debugging loop；那屬於 Phase 5B。

最後請回報完整的 Phase 5A Real-Agent Acceptance Report，不要只回報 PASS/FAIL。