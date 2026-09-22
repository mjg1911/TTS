# Windows Kokoro Release Acceptance Checklist

- Tester:
- Date:
- Artifact SHA-256:
- Windows version:
- Result: PASS / FAIL
- Notes:

## Procedure

1. Restore a clean Windows VM snapshot with no Python/Kokoro/spaCy/espeak-ng.
2. Choose acceptance mode `Portable` or `Installer`, copy only that release artifact to the VM, and record its SHA-256.
3. Disable the VM network adapter before the first application/install action.
4. For `Installer`, run `PiperTraySetup.exe` with networking disabled; for `Portable`, run `PiperTray.exe` directly.
5. Launch the tray and verify it remains responsive and the Kokoro payload is bootstrapped locally without network access.
6. Open Settings; verify Speech engine contains Piper and Kokoro.
7. Select Kokoro; verify voice control contains `af_heart` and has no model/voice browse button.
8. Apply and synthesize a sentence successfully.
9. Configure a Piper voice, apply it, and synthesize successfully.
10. Switch back to Kokoro and verify `af_heart` is restored; switch to Piper and verify its prior model is restored.
11. Start a long Kokoro sentence, cancel it, and verify playback stops while the tray remains responsive.
12. Restart the app with networking still disabled and synthesize through Kokoro again.
13. With Kokoro active and `KokoroWorker.exe` visible in Task Manager, forcibly terminate `PiperTray.exe`; verify `KokoroWorker.exe` disappears within 5 seconds. This is the Job Object crash-orphan acceptance check.
14. Relaunch normally, activate Kokoro, exit through the tray UI, and verify no `KokoroWorker.exe` remains.
15. Corrupt one installed Kokoro asset without deleting the installation root, relaunch, and verify a clear Kokoro-unavailable state, successful Piper use, no helper process, and that the corrupted bytes are not automatically repaired.
16. Verify no external connection attempts occurred during first launch, Settings changes, synthesis, worker restart, forced tray crash, or corrupt-asset handling.
17. Record PASS/FAIL and notes for this artifact mode.
18. Restore the clean snapshot and repeat steps 2–17 with the other artifact mode so both `PiperTray.exe` and `PiperTraySetup.exe` are independently accepted offline.
