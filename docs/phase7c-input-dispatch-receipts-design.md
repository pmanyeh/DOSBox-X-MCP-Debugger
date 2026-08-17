# Phase 7C: input dispatch receipts (Epic C)

> Scope: Epic C of
> `docs/phase7-observability-and-autonomous-control-requirements.md`
> (receipt fields on every `input.key.*`/`input.mouse.*` response, plus
> `input.receipt.get`).
> Status: design, grounded in the Phase 7B implementation this builds on.
> Not yet implemented.

## Goal

Let an agent confirm that a specific keypress/click it sent was
actually handed to DOSBox-X's own input entry points
(`KEYBOARD_AddKey()`/`Mouse_CursorMoved()`/`Mouse_ButtonPressed()`/
`Mouse_ButtonReleased()`), by `input_sequence`, after the fact -- not
just at the moment of the original call. Every `input.*` response
already implicitly means "dispatched" today (the RPC only returns once
`DEBUG_AI_CheckPendingInput()` has run the op), but there is currently
no way to look that fact up again later, and no monotonic id tying
separate calls together. `guest_observed` (whether the DOS/BIOS input
layer visibly picked it up) is explicitly optional/best-effort in the
requirements draft (section 5.2) -- this phase reserves the field but
does not implement real observation.

## Data model: a plain mutex-guarded ring buffer, not a third queue

Unlike Phase 7B's `capture.get`/`.set`, this needs no dual-route
threading design: a receipt is a small, immutable record of something
that ALREADY happened (a completed dispatch), not a live read of
emulator/window state. It never needs emulator-thread execution to
answer -- only safe concurrent access to already-computed data. So
`input.receipt.get` is answered directly from the socket thread that
receives it (like `debug.status`'s "not stopped" fast path), guarded by
one new mutex, with no new queue and no involvement of `g_requestQueue`/
`g_pendingInputs`:

```cpp
struct InputReceipt {
    uint64_t sequence;
    std::string device;              // "keyboard" | "mouse"
    bool dispatched;                 // always true -- only recorded after a
                                      // real KEYBOARD_AddKey()/Mouse_*() call
    uint64_t dispatchedAtEmulatedMs; // PIC_FullIndex() at dispatch time
    std::chrono::steady_clock::time_point recordedAt; // for the 10-minute cap
};

static std::mutex g_receiptMutex;
static std::deque<InputReceipt> g_receipts;
```

Written ONLY from `DEBUG_AI_CheckPendingInput()` (the emulator thread --
every guest-input-dispatching op, Phase 6B's and Phase 7B's alike, goes
through this one function; `DEBUG_AI_Poll()`/`g_requestQueue` never
dispatch guest input, so no second writer exists). Read from socket
threads via `input.receipt.get`. The mutex is held only for a
push_back/linear-scan/pop_front, never across a blocking wait, so
contention with the emulator thread's own (separate, brief) lock
acquisition is not a concern.

### Eviction

The requirements draft (section 5.2): "at least the most recent 4096
entries, or the most recent 10 minutes, whichever limit is hit first."
Implemented as two independent, unconditional trims on every insert --
an entry is evicted as soon as EITHER bound is exceeded for it, not
only when both are:

```cpp
static const size_t   MAX_RECEIPTS = 4096;
static const std::chrono::minutes RECEIPT_MAX_AGE{10};

static void RecordInputReceipt(uint64_t seq, const char *device, uint64_t dispatchedAtMs) {
    std::lock_guard<std::mutex> lk(g_receiptMutex);
    auto now = std::chrono::steady_clock::now();
    while (!g_receipts.empty() && (now - g_receipts.front().recordedAt) > RECEIPT_MAX_AGE)
        g_receipts.pop_front();
    while (g_receipts.size() >= MAX_RECEIPTS)
        g_receipts.pop_front();
    g_receipts.push_back({seq, device, true, dispatchedAtMs, now});
}
```

A lookup for a `input_sequence` no longer present (evicted, or never
issued -- both are indistinguishable, deliberately: this bridge does
not track "highest sequence ever issued" separately, so a stale AND a
bogus id both just report as absent) returns `INPUT_RECEIPT_EXPIRED`,
per the draft's acceptance criterion 5.3.3.

## What gets a receipt, and what deliberately does not

The requirements draft's section 5.1 scopes this to "every `input.key.*`
and `input.mouse.*`" response. Read literally against the actual method
names in this bridge:

- **Gets a receipt**: `input.key.down/up/tap`, `input.mouse.move_relative`,
  `input.mouse.button.set/click`, `input.mouse.move_absolute`,
  `input.mouse.click_at` -- every one of these calls
  `KEYBOARD_AddKey()`/`Mouse_CursorMoved()`/`Mouse_ButtonPressed()`/
  `Mouse_ButtonReleased()`, exactly section 5.2's `dispatched=true`
  condition list.
- **Does NOT get a receipt, despite matching the `input.mouse.*` name
  prefix**: `input.mouse.capture.get`/`.set` (Phase 7B). Neither calls
  any of the four functions above -- they call `GFX_CaptureMouse()`,
  window/SDL state, not guest input. Attaching a "dispatch receipt" to
  a call that never dispatched anything to the guest would be exactly
  the kind of fake-success claim section 2.1 of the requirements draft
  warns against generally. `capture.get` is a status read, not a
  dispatch, and already has its own well-defined result shape from
  Phase 7B.
- **Does NOT get a receipt**: `input.release_all` -- its native method
  name is neither `input.key.*` nor `input.mouse.*`, and it releases an
  arbitrary number of previously-held keys/buttons at once, so a single
  `input_sequence` would not describe any one of them meaningfully.

## API (from the Phase 7 draft, section 5.1, unchanged)

Every successful response from the methods in the first bullet above
gains, inside its existing `result` object (not a new top-level shape):

```json
{
  "queued": true,
  "dispatched": true,
  "dispatched_at_emulated_ms": 98765,
  "input_sequence": 1234,
  "guest_observed": "not_supported"
}
```

(`input.mouse.move_absolute`/`click_at` already had `queued`/
`dispatched`/`input_sequence` from Phase 7B -- this adds the two new
fields to their existing result rather than duplicating the other
three.) `guest_observed` is always `"not_supported"` in this
implementation -- the draft's section 5.2 explicitly allows a v1 to
implement only `queued`/`dispatched` as long as the schema reserves the
field, which this satisfies without claiming an observation capability
that does not exist yet.

New method:

```text
input.receipt.get
params: { "input_sequence": uint64 }
result:
{
  "input_sequence": uint64,
  "queued": true,
  "dispatched": true,
  "dispatched_at_emulated_ms": uint64,
  "guest_observed": "not_supported",
  "device": "keyboard" | "mouse",
  "guest_observation": { "kind": null, "observed_at_emulated_ms": null }
}
```

Error `INPUT_RECEIPT_EXPIRED` if `input_sequence` is not currently in
the ring buffer (evicted or never issued).

## Shared sequence counter

Phase 7B already introduced `g_nextInputSequence` (a
`std::atomic<uint64_t>`) for `move_absolute`/`click_at`. This phase
extends its use to every other dispatching op above, so `input_sequence`
is one shared, monotonically increasing space across all of
`input.key.*`/`input.mouse.*`, not a per-method counter -- matching the
draft's implication that a single `input.receipt.get` call can look up
a receipt from any of them.

## Implementation touches (three files)

1. `dosbox-src/src/debug/debug_ai.cpp`: `InputReceipt`/`g_receiptMutex`/
   `g_receipts`, `RecordInputReceipt()`/`LookupInputReceipt()`, extend
   every dispatching case in `DEBUG_AI_CheckPendingInput()`'s switch to
   allocate a sequence, record a receipt, and include the five new
   fields in its response; new `input.receipt.get` branch in
   `HandleLine()`, answered directly (no queue).
2. `ai/dosbox_client.py`: every existing input method's docstring/return
   shape gains a note about the new fields; new `get_input_receipt()`;
   new `DOSBoxInputReceiptExpired` exception.
3. `ai/server.py`: new `get_input_receipt` MCP tool;
   `AGENT_GUIDE.md`/`.zh-TW.md`, `README.md`/`.zh-TW.md` tool-count and
   reference updates; `CHANGELOG.md` entry.

## Verification plan

1. `key_tap("enter")`, then `input.receipt.get` with the returned
   `input_sequence` -- `dispatched: true`, `device: "keyboard"`.
2. Same for a `click_at` and a `move_mouse_relative` --
   `device: "mouse"` both times.
3. A `input.receipt.get` for an `input_sequence` that was never issued
   -- `INPUT_RECEIPT_EXPIRED`.
4. `input.mouse.capture.get`/`.set` responses do NOT gain receipt
   fields (confirms the scoping decision above is actually followed in
   code, not just documented).
5. `input_sequence` values are strictly increasing across a mix of key
   and mouse dispatches on one connection.

## Implementation status: done, verified live

Implemented as designed, in `dosbox-src/src/debug/debug_ai.cpp`,
`ai/dosbox_client.py`, and `ai/server.py`. Built clean (0 errors, 0 new
warnings) against the `Release` (SDL1) `x64` configuration.

Verified live via the actual MCP tool functions against a running
`dosbox-x.exe`, covering every item in the verification plan above:

1. `key_tap("enter")` returned `input_sequence: 1`;
   `get_input_receipt(1)` returned `dispatched: true`,
   `device: "keyboard"`, matching `dispatched_at_emulated_ms`.
2. `click_at(100, 50)` returned `input_sequence: 2`; its receipt
   reported `device: "mouse"`.
3. `get_input_receipt(999999999)` (never issued) ->
   `INPUT_RECEIPT_EXPIRED`.
4. `get_mouse_capture`/`set_mouse_capture` responses confirmed to carry
   NO `input_sequence`/receipt fields, and `release_all_input`
   confirmed to carry none either -- the scoping decision above holds
   in the actual running code, not just the design.
5. `move_mouse_relative` (a third, different op) returned
   `input_sequence: 3` -- confirms the counter is one shared space
   across key/mouse ops in dispatch order, not per-method.

In a follow-up session (after root-causing and fixing an unrelated
debugger-console crash that had been blocking a genuinely stopped
debugger state -- see `CHANGELOG.md`'s "Bridge fix -- debugger console
crash on piped/redirected stdio" entry), also verified while
genuinely stopped (`execution.pause` then `debug.status` confirmed
`stopped: true`):

6. `input.receipt.get` answered correctly while stopped (a query for an
   unissued sequence still correctly returned `INPUT_RECEIPT_EXPIRED`),
   confirming it needs no request queue in either debugger state, as
   designed.
7. `key_tap` (Phase 6B) correctly rejected with `DEBUGGER_STOPPED`
   while stopped, alongside `move_absolute`/`click_at` (Phase 7B) --
   no receipt was recorded for the rejected calls.

Not yet done: an automated `pytest` suite (consistent with the same
gap already tracked for Phases 6A/6B/7A/7B) and stress-testing the
ring buffer's two eviction bounds (4096 entries / 10 minutes) under
sustained load -- both live runs above stayed well under either bound.
