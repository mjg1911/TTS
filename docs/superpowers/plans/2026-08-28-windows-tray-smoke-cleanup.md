# Windows Tray Smoke Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make frozen Windows tray smoke-test teardown tolerate the brief period Windows needs to release `piper-tray.log`.

**Architecture:** Keep the runtime unchanged. Update the PowerShell smoke harness so process termination is followed by a bounded exit wait and bounded recursive-delete retries; extend the existing packaging contract test to protect that cleanup behavior.

**Tech Stack:** PowerShell, Python, pytest.

## Global Constraints

- Change only the smoke harness and its packaging contract test.
- Preserve startup readiness checks and environment restoration.
- Cleanup must be bounded and must surface persistent deletion failures.

---

### Task 1: Add the cleanup contract regression test

**Files:**
- Modify: `C:\PrOgram project\Piper\tests\windows_tray\test_packaging_contract.py`
- Test: `C:\PrOgram project\Piper\tests\windows_tray\test_packaging_contract.py`

**Interfaces:**
- Consumes: the smoke script text and its `finally` block, using the file's existing source-contract testing style.
- Produces: a failing test requiring process-exit waiting and bounded cleanup retries.

- [ ] **Step 1: Write the failing test**

Add a test that extracts the `finally` block and asserts it contains `WaitForExit`, a bounded retry loop, and `Start-Sleep` inside cleanup. Keep the assertions about the existing `$SmokeRoot` deletion intact.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```text
pytest tests/windows_tray/test_packaging_contract.py -q
```

Expected: the new cleanup-contract test fails because the current script stops the process and immediately calls `Remove-Item`.

- [ ] **Step 3: Commit the failing test**

```text
git add tests/windows_tray/test_packaging_contract.py
git commit -m "test: cover windows tray smoke cleanup timing"
```

### Task 2: Implement bounded process and directory cleanup retries

**Files:**
- Modify: `C:\PrOgram project\Piper\script\smoke_windows_tray.ps1` in the `finally` block.

**Interfaces:**
- Consumes: `$Process` and `$SmokeRoot` already established by the smoke script.
- Produces: teardown that waits for process exit and retries deletion for a bounded interval.

- [ ] **Step 1: Add the minimal implementation**

After `Stop-Process -Id $Process.Id -Force`, call `$Process.WaitForExit(10000)`. Replace the one-shot directory deletion with a loop that attempts `Remove-Item -Recurse -Force $SmokeRoot`, breaks on success, sleeps one second between attempts, and throws the final deletion error after 10 attempts. Keep environment restoration outside the deletion retry and inside the outer `finally` nesting.

- [ ] **Step 2: Run the focused contract test**

Run:

```text
pytest tests/windows_tray/test_packaging_contract.py -q
```

Expected: all packaging contract tests pass.

- [ ] **Step 3: Commit the implementation**

```text
git add script/smoke_windows_tray.ps1 tests/windows_tray/test_packaging_contract.py
git commit -m "fix: make windows tray smoke cleanup resilient"
```

### Task 3: Verify the Windows-tray test surface

**Files:**
- Verify: `C:\PrOgram project\Piper\script\smoke_windows_tray.ps1`
- Verify: `C:\PrOgram project\Piper\tests\windows_tray\`

- [ ] **Step 1: Run the complete Windows-tray tests**

Run:

```text
pytest tests/windows_tray -q
```

Expected: exit code 0 with no failures.

- [ ] **Step 2: Inspect the final diff**

Run:

```text
git diff HEAD~1 --check
git status --short
```

Expected: no whitespace errors; only the intended smoke script, contract test, and plan/spec commits are present.
