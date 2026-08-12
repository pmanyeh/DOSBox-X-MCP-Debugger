"""
Minimal native bridge test client (Phase 3B).

Connects directly to the DOSBox-X native AI bridge over newline-delimited
JSON TCP (127.0.0.1:9876) and exercises the five read-only Phase 3B
methods: debug.status, cpu.get, memory.read, code.current,
code.disassemble.

This is NOT a mocked unit test -- it requires a real, running DOSBox-X
with the debugger active (Ctrl+Pause, or started with -break-start), so
that DEBUG_Loop() -- and therefore DEBUG_AI_Poll() -- is actually running
and can service requests. Run it directly:

    .\\.venv\\Scripts\\python.exe tests\\test_native_bridge.py [host] [port]

It prints PASS/FAIL for each check and exits non-zero if anything failed.
Each check verifies: the response is valid JSON, its "id" echoes the
request's "id", it has an "ok" field, and (on success) the result has the
shape Phase3.md specifies -- not just that *some* JSON came back.
"""

import json
import socket
import sys

HOST_DEFAULT = "127.0.0.1"
PORT_DEFAULT = 9876
TIMEOUT_SECONDS = 10


class BridgeClient:
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=TIMEOUT_SECONDS)
        self.sock.settimeout(TIMEOUT_SECONDS)
        self._buf = b""
        self._next_id = 1

    def request(self, method, params=None):
        req_id = self._next_id
        self._next_id += 1
        payload = {"id": req_id, "method": method}
        if params is not None:
            payload["params"] = params
        line = json.dumps(payload) + "\n"
        self.sock.sendall(line.encode("utf-8"))
        return req_id, self._read_line()

    def _read_line(self):
        while b"\n" not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("bridge closed the connection")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line.decode("utf-8")

    def close(self):
        self.sock.close()


class Reporter:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def check(self, description, condition):
        if condition:
            self.passed += 1
            print(f"PASS: {description}")
        else:
            self.failed += 1
            print(f"FAIL: {description}")
        return condition

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{self.passed}/{total} checks passed")
        return self.failed == 0


def is_hex(s, expected_len=None):
    if not isinstance(s, str):
        return False
    if expected_len is not None and len(s) != expected_len:
        return False
    try:
        int(s, 16)
        return True
    except ValueError:
        return False


def run(host, port):
    r = Reporter()
    client = BridgeClient(host, port)
    print(f"Connected to native AI bridge at {host}:{port}\n")

    # -- debug.status -----------------------------------------------
    req_id, raw = client.request("debug.status")
    print(f"--> debug.status\n<-- {raw}")
    try:
        resp = json.loads(raw)
        r.check("debug.status: response is valid JSON", True)
    except json.JSONDecodeError:
        r.check("debug.status: response is valid JSON", False)
        resp = {}
    r.check("debug.status: response id matches request id", resp.get("id") == req_id)
    r.check("debug.status: response has \"ok\" field", "ok" in resp)
    if resp.get("ok"):
        result = resp.get("result", {})
        r.check("debug.status: result has \"stopped\" (bool)", isinstance(result.get("stopped"), bool))
        loc = result.get("location", {})
        r.check("debug.status: location.cs is 4 hex digits", is_hex(loc.get("cs"), 4))
        r.check("debug.status: location.eip is 4 hex digits", is_hex(loc.get("eip"), 4))
        instr = result.get("instruction", {})
        r.check("debug.status: instruction.text is non-empty", bool(instr.get("text")))
        regs = result.get("registers", {})
        r.check("debug.status: registers.eax is 8 hex digits", is_hex(regs.get("eax"), 8))
        segs = result.get("segments", {})
        r.check("debug.status: segments.ss is 4 hex digits", is_hex(segs.get("ss"), 4))
        print(f"    real CS:EIP = {loc.get('cs')}:{loc.get('eip')}  instruction = {instr.get('text')!r}")
    else:
        print(f"    (debug.status returned an error -- is the DOSBox-X debugger active? "
              f"{resp.get('error')})")
    print()

    # -- cpu.get ------------------------------------------------------
    req_id, raw = client.request("cpu.get")
    print(f"--> cpu.get\n<-- {raw}")
    try:
        resp = json.loads(raw)
        r.check("cpu.get: response is valid JSON", True)
    except json.JSONDecodeError:
        r.check("cpu.get: response is valid JSON", False)
        resp = {}
    r.check("cpu.get: response id matches request id", resp.get("id") == req_id)
    r.check("cpu.get: response has \"ok\" field", "ok" in resp)
    if resp.get("ok"):
        result = resp.get("result", {})
        expected_32bit = ["eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp", "eflags"]
        expected_16bit = ["cs", "ds", "es", "ss", "fs", "gs", "eip"]
        r.check("cpu.get: all 32-bit fields present and 8 hex digits",
                all(is_hex(result.get(k), 8) for k in expected_32bit))
        r.check("cpu.get: all segment/EIP fields present and 4 hex digits",
                all(is_hex(result.get(k), 4) for k in expected_16bit))
        print(f"    real CPU state: eax={result.get('eax')} cs={result.get('cs')} eip={result.get('eip')}")
    print()

    # -- code.current ---------------------------------------------------
    req_id, raw = client.request("code.current")
    print(f"--> code.current\n<-- {raw}")
    try:
        resp = json.loads(raw)
        r.check("code.current: response is valid JSON", True)
    except json.JSONDecodeError:
        r.check("code.current: response is valid JSON", False)
        resp = {}
    r.check("code.current: response id matches request id", resp.get("id") == req_id)
    r.check("code.current: response has \"ok\" field", "ok" in resp)
    current_address = None
    if resp.get("ok"):
        result = resp.get("result", {})
        current_address = result.get("address")
        r.check("code.current: result has \"address\" like SEG:OFF", isinstance(current_address, str) and ":" in (current_address or ""))
        r.check("code.current: result has non-empty \"bytes\"", bool(result.get("bytes")))
        r.check("code.current: result has non-empty \"instruction\"", bool(result.get("instruction")))
        print(f"    real instruction @ {current_address}: {result.get('bytes')}  =>  {result.get('instruction')}")
    print()

    # -- memory.read ------------------------------------------------
    mem_address = current_address or "0000:0000"
    req_id, raw = client.request("memory.read", {"address": mem_address, "length": 16})
    print(f"--> memory.read({mem_address}, 16)\n<-- {raw}")
    try:
        resp = json.loads(raw)
        r.check("memory.read: response is valid JSON", True)
    except json.JSONDecodeError:
        r.check("memory.read: response is valid JSON", False)
        resp = {}
    r.check("memory.read: response id matches request id", resp.get("id") == req_id)
    r.check("memory.read: response has \"ok\" field", "ok" in resp)
    if resp.get("ok"):
        result = resp.get("result", {})
        bts = result.get("bytes", [])
        r.check("memory.read: result.length == 16", result.get("length") == 16)
        r.check("memory.read: result.bytes has 16 entries, each 2 hex digits",
                len(bts) == 16 and all(is_hex(b, 2) for b in bts))
        print(f"    real memory @ {mem_address}: {' '.join(bts)}")
    print()

    # -- code.disassemble -----------------------------------------------
    req_id, raw = client.request("code.disassemble", {"address": mem_address, "count": 5})
    print(f"--> code.disassemble({mem_address}, 5)\n<-- {raw}")
    try:
        resp = json.loads(raw)
        r.check("code.disassemble: response is valid JSON", True)
    except json.JSONDecodeError:
        r.check("code.disassemble: response is valid JSON", False)
        resp = {}
    r.check("code.disassemble: response id matches request id", resp.get("id") == req_id)
    r.check("code.disassemble: response has \"ok\" field", "ok" in resp)
    if resp.get("ok"):
        result = resp.get("result", [])
        r.check("code.disassemble: result is a list of 5 instructions", isinstance(result, list) and len(result) == 5)
        r.check("code.disassemble: every entry has address/bytes/instruction",
                all(isinstance(e, dict) and e.get("address") and e.get("bytes") and e.get("instruction") for e in result))
        for entry in result:
            print(f"    {entry.get('address')}: {entry.get('bytes'):<12} {entry.get('instruction')}")
    print()

    # -- error handling sanity check: unknown method ---------------------
    req_id, raw = client.request("no.such.method")
    print(f"--> no.such.method\n<-- {raw}")
    try:
        resp = json.loads(raw)
        r.check("unknown method: response is valid JSON", True)
    except json.JSONDecodeError:
        r.check("unknown method: response is valid JSON", False)
        resp = {}
    r.check("unknown method: response id matches request id", resp.get("id") == req_id)
    r.check("unknown method: ok is false", resp.get("ok") is False)
    r.check("unknown method: error.code == UNKNOWN_METHOD", resp.get("error", {}).get("code") == "UNKNOWN_METHOD")
    print()

    # -- execution.pause while already stopped (Phase 4C) ----------------
    req_id, raw = client.request("execution.pause")
    print(f"--> execution.pause (already stopped)\n<-- {raw}")
    resp = json.loads(raw)
    r.check("execution.pause (already stopped): ok is false", resp.get("ok") is False)
    r.check("execution.pause (already stopped): error.code == ALREADY_STOPPED",
            resp.get("error", {}).get("code") == "ALREADY_STOPPED")
    print()

    # -- execution.continue / execution.pause round trip (Phase 4C) ------
    # NOTE: from this point on, CS:EIP is permanently moved away from the
    # F000:FFF0 reset vector the checks above depended on -- this section
    # must stay last in this script, same reasoning as
    # tests/test_mcp_native_bridge.py's Phase 4C section.
    req_id, raw = client.request("execution.continue")
    print(f"--> execution.continue\n<-- {raw}")
    resp = json.loads(raw)
    r.check("execution.continue: response id matches request id", resp.get("id") == req_id)
    r.check("execution.continue: ok is true", resp.get("ok") is True)
    if resp.get("ok"):
        result = resp.get("result", {})
        r.check("execution.continue: result.running is true", result.get("running") is True)
        r.check("execution.continue: result.stopped is false", result.get("stopped") is False)
    print()

    req_id, raw = client.request("execution.continue")
    print(f"--> execution.continue (already running)\n<-- {raw}")
    resp = json.loads(raw)
    r.check("execution.continue (already running): ok is false", resp.get("ok") is False)
    r.check("execution.continue (already running): error.code == ALREADY_RUNNING",
            resp.get("error", {}).get("code") == "ALREADY_RUNNING")
    print()

    req_id, raw = client.request("debug.status")
    print(f"--> debug.status (while running)\n<-- {raw}")
    resp = json.loads(raw)
    r.check("debug.status (while running): ok is true", resp.get("ok") is True)
    if resp.get("ok"):
        result = resp.get("result", {})
        r.check("debug.status (while running): result.running is true", result.get("running") is True)
        r.check("debug.status (while running): result.stopped is false", result.get("stopped") is False)
        r.check("debug.status (while running): no fabricated register snapshot",
                "registers" not in result)
    print()

    req_id, raw = client.request("execution.pause")
    print(f"--> execution.pause\n<-- {raw}")
    resp = json.loads(raw)
    r.check("execution.pause: response id matches request id", resp.get("id") == req_id)
    r.check("execution.pause: ok is true", resp.get("ok") is True)
    if resp.get("ok"):
        result = resp.get("result", {})
        r.check("execution.pause: result.stopped is true", result.get("stopped") is True)
        r.check("execution.pause: result has real registers.eax (8 hex digits)",
                is_hex(result.get("registers", {}).get("eax"), 8))
        print(f"    real CS:EIP after pause = {result.get('location', {}).get('cs')}:"
              f"{result.get('location', {}).get('eip')}")
    print()

    client.close()
    return r.summary()


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else HOST_DEFAULT
    port = int(sys.argv[2]) if len(sys.argv) > 2 else PORT_DEFAULT
    try:
        ok = run(host, port)
    except (ConnectionError, OSError) as e:
        print(f"Could not reach the native AI bridge at {host}:{port}: {e}")
        print("Is DOSBox-X running with the debugger active?")
        sys.exit(2)
    sys.exit(0 if ok else 1)
