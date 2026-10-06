# Piper Tray 1.10.0 release verification

Verified on Windows x64 on 2026-10-06, on branch `worker`.

## Release artifacts

| Artifact | Bytes |
| --- | ---: |
| PiperTraySetup-1.10.0.exe | 122,411,598 |
| PiperTray-1.10.0-windows-x64.zip | 139,929,438 |
| Shared worker, two parts | 2,680,604,889 |
| Nano model, one part | 1,801,986,659 |
| Turbo model, two parts | 2,771,812,864 |

Every model/worker part is at most 1,900,000,000 bytes. All local parts were freshly rehashed after generation and matched the bundled catalog's SHA-256 and sizes. The catalog uses this repository's fixed `v1.10.0` GitHub release URLs. `SHA256SUMS.txt` covers the app, installer, catalog, and model/worker parts.

The shared worker was freshly built from the pinned Chatterbox/Perth sources with Torch 2.6.0+cu124. Staging and archive preparation checked all pinned model files and the complete version 2 shared payload inventory. The base app contains neither the Chatterbox payload nor Torch; its unpacked size is 228,993,523 bytes.

## Packaged checks

- PyInstaller app build and Inno Setup installer compilation succeeded.
- The actual frozen app ran from an empty working directory with empty task-local APPDATA/LOCALAPPDATA and offline flags. It found the bundled Alba model, generated 46,848 audio samples, checked all five catalog parts, and constructed/closed the real Tk download panel.
- The portable ZIP passed its complete CRC and inventory check. Its extracted executable independently passed the same offline diagnostic, generating 46,336 audio samples.
- The real downloader consumed the generated worker/Nano archive parts, verified them, and activated a local generation. Nano CPU inference from that generation produced 84,480 PCM bytes; another run with a fresh writable cache produced 76,800 bytes. An initial harness run with the sandbox's restricted default user profile timed out during startup; repeat checks with writable task-local app data passed.
- Adding Turbo consumed only its two model parts, retained Nano, and reused the shared worker. Actual Turbo CUDA inference from the activated generation produced 122,880 PCM bytes at 24,000 Hz. A subsequent call for each installed engine used a transport that raises on any network request; both reused the active local generation successfully.
- Separate packaged-worker checks also produced Nano CUDA audio (136,320 PCM bytes), Turbo CUDA audio (132,480 bytes), and Nano CPU audio (113,280 bytes). CUDA hardware was an NVIDIA GeForce RTX 4070. CPU and CUDA PCM was nonempty and nonsilent.

## Automated checks and review

- Release/entry-point/packaging checks: 59 passed. Downloader/discovery/release checks after the final fix: 36 passed. UI checks and standalone real Tk Settings layouts passed.
- Final Windows tray and Turbo regression run: **1,047 passed, 17 failed, 2 skipped**. The exact 17 failure names match the pre-change baseline: one app-foundation fixture, twelve hotkey fixtures, three settings-schema expectations, and one Turbo delivery-mode fixture. No new failing tests remain.
- Independent scoped and cumulative reviews covered downloader integrity, UI threading/cancellation/gating, packaging, and catalog compatibility. The cumulative review caught a legacy-discovery regression after a failed first download; a failing reproduction for both engines was added and the fix passed re-review. Empty generation stores now allow legacy installations to be discovered.

Release publication should use the verified app files and every catalog-listed part together. This report records local build verification; remote upload verification is performed before publication.
