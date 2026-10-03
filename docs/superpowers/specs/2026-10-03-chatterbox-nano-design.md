# Chatterbox Nano integration

## Objective

Add Chatterbox Nano as a third local speech engine to the Windows tray app on the current Chatterbox branch. The first version uses only the built-in default voice, as requested. Existing Piper and Kokoro settings remain readable. Selected text, replay, browser speech, and Codex speech all use the selected engine through the existing speech queue.

## Approach

Recommended: a dedicated Nano worker process with its own dependency environment and packaged executable. This follows the existing Kokoro isolation pattern and avoids mixing incompatible Torch, Transformers, and NumPy requirements into the tray runtime.

Alternatives: importing Chatterbox directly into the tray simplifies initial wiring but adds heavy dependencies and complicates cancellation and unloading. Calling an external TTS server requires another service and changes the app's self-contained local operation.

## User experience

Add Chatterbox Nano to the engine selector. Show its built-in default voice and explain that Nano supports English. Preserve Piper and Kokoro voice choices when switching engines. Use existing playback controls for speed and pitch, rather than exposing unsupported Nano exaggeration or CFG controls. Preserve supported paralinguistic tags in synthesis text.

Prepare and validate a replacement backend before committing an engine change. On preparation failure, retain the previous working backend and show a non-blocking error. On startup with Nano selected, keep the tray responsive while Nano loads and use Piper as recovery if preparation fails.

## Runtime

Load the official ChatterboxTurboTTS.from_local(model_directory, device="cpu", nano=True) API inside the worker. Require the Nano checkpoint, voice encoder, meanflow generator, tokenizer assets, and default voice conditionals. Model loading and synthesis happen outside the UI thread; inference uses Torch inference mode.

Convert generated waveform audio into the existing PCM playback interface using the model's reported sample rate. Split long input into bounded sentence chunks to avoid upstream truncation and begin playback before the entire selection is synthesized. Check cancellation between chunks. Interruption during model inference terminates and recreates the worker so Stop remains responsive. Suppress stale audio through existing request generations.

Tie worker lifetime to tray shutdown. Retain existing backend lease handling when switching engines, so resources close safely after active requests finish.

## Assets and distribution

Pin upstream code and model revisions that support nano=True; a package version alone does not prove Nano API compatibility. Add dedicated worker requirements, build and staging scripts, payload collection, and an installation manifest following Kokoro packaging conventions. Validate required files and hashes before reporting Nano available.

Stage models during explicit setup or build, then load only local assets during normal speech. Include required dependency resources in the worker distribution and preserve upstream watermarking. Document setup and runtime limitations in README.md.

## Verification

Cover settings compatibility and round trips, engine selection, backend switching and rollback, startup recovery, waveform conversion, long-text chunking, cancellation, worker cleanup, and packaging contracts. Run existing tray tests to detect regressions in Piper, Kokoro, and shared playback.

Perform a real CPU synthesis smoke test with pinned models and dependencies if they can be provisioned here. Report real inference and packaged-executable verification separately from mocked tests; unit-test success does not imply either.

## Scope

CPU inference and the built-in default voice. Reference-recording support, GPU selection, voice libraries, training, multilingual Chatterbox, and external servers are outside this first integration.

## Upstream references

- https://github.com/resemble-ai/chatterbox/blob/master/example_tts_nano.py
- https://github.com/resemble-ai/chatterbox/blob/master/src/chatterbox/tts_turbo.py
- https://huggingface.co/ResembleAI/chatterbox-nano
