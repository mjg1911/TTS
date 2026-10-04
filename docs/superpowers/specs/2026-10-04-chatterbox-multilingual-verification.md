# Multilingual V3 verification

Verified on 2026-10-04 on branch `Chatterbox-500`.

- Full project suite: **904 passed, 2 skipped**, using the project test environment.
- Independent review: no blocking or functional findings.
- Real NVIDIA RTX 4070 inference: explicitly loaded V3 on CUDA and generated English, Dutch, and Chinese PCM audio with offline model/tokenizer assets.
- PyInstaller worker build succeeded. The packaged worker generated Japanese audio at 24 kHz with expressiveness 0.7 and guidance 0.3. A second synthesis reused the loaded worker process.
- The packaged test exposed a compiled tokenizer dependency on `srsly`; the final build explicitly collects it, alongside Japanese dictionary data from `pykakasi`.
- Final offline payload staging succeeded from local pinned weights and the Chinese segmenter archive. The current generated payload is `build/multilingual-payload`.

Unit and integration tests cover CUDA rejection, explicit V3 selection, control validation/forwarding, settings persistence, UI visibility, failed-change rollback, worker framing/cancellation, and offline payload validation. Real inference checks confirm nonempty audio; they do not assess every language's pronunciation. The full tray application and installer were not rebuilt or installed as part of this change.
