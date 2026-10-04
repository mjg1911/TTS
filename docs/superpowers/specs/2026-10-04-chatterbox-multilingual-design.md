# Chatterbox Multilingual V3

Approved by the user on 2026-10-04 in chat. Add Chatterbox Multilingual V3 (500M) as a separate engine on the current branch. It requires an NVIDIA CUDA GPU: unavailable CUDA and CUDA initialization failures must fail readiness without CPU fallback. Failed changes preserve the current working backend and saved settings.

Place Language (23 upstream languages, English default), Expressiveness (0.25–2, default 0.5), and Voice/style guidance (0–1, default 0.5) in the engine options. Show numeric slider values and persist selections across restarts. These controls apply only to Multilingual. Map them to language_id, exaggeration, and cfg_weight. Continue supporting managed custom WAV references, speed, pitch, stop, replay, and automatic reading.

Use a separate offline worker and hashed, revision-pinned model payload following Nano's existing process and framing conventions. Explicitly load t3_model='v3'; upstream defaults to V2. Reuse framing and cancellation behavior without changing Nano defaults or CPU fallback. Package the model and CUDA runtime using explicit build/staging scripts; runtime must not download dependencies or weights.

Validate settings, CUDA enforcement, V3 selection, worker protocol, failed apply rollback, engine switching, and UI visibility. Run the relevant worker and tray regression suites. Report any limits of real GPU verification.
