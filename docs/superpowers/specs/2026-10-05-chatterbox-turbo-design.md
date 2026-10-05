# Replace Multilingual with Chatterbox Turbo

The user authorized implementation in the current branch. The engine lineup is Piper, Chatterbox Nano, and Chatterbox Turbo (350M). Replace Multilingual V3 rather than adding a fourth engine.

Turbo uses the existing pinned Chatterbox source, ChatterboxTurboTTS.from_local with nano=False, and a separately pinned ResembleAI/chatterbox-turbo payload. Retain CUDA-only behavior, offline loading, managed custom WAV references, rollback on failed readiness, and the existing speech controls. Nano and Piper keep their existing behavior.

Turbo is English-only and ignores exaggeration and CFG guidance. Remove Multilingual language/style controls and protocol options. Migrate saved Multilingual engine selections to Turbo, discarding retired options. Update startup choices, settings, diagnostics, build/staging scripts, packaging, tests, and README. Verify regression tests and GPU synthesis if the local environment supports it.
