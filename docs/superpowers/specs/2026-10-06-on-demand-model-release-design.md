# Piper 1.10.0: downloadable Chatterbox models

Work stays on the current `worker` branch. Existing unrelated local files are preserved.

## User experience

The Windows app ships with Piper and the existing default voice, `en_GB-alba-medium`, including its ONNX configuration. A fresh installation can speak immediately without internet access. Piper remains the default engine. Preserve the existing startup model chooser, with Piper selected by default on a fresh installation.

Selecting Chatterbox Nano or Chatterbox Turbo in the startup chooser or Settings shows a Download button when the selected engine is not installed. No download starts merely from selecting an engine. Installed engines can be selected without a network request. Downloads show progress and a useful failure message, permit retry, and do not freeze the interface. Closing the download UI cancels pending work safely. The user can start the selected engine after installation; normal Settings Save behavior remains.

Turbo's existing NVIDIA CUDA requirement and Nano's existing CPU/GPU behavior remain in effect. Downloading Turbo does not establish GPU compatibility.

## Recommended distribution

Publish versioned release assets in `mjg1911/TTS`: the Piper installer and portable app, a shared Chatterbox worker archive, separate Nano and Turbo model archives, and checksums. The app uses a bundled catalog with fixed release URLs, archive sizes and SHA-256 digests. Runtime download sources are this repository's GitHub release assets; upstream model downloads are only part of release preparation.

Separate archives allow the worker to be installed once and each model independently. Alternatives are a complete worker-and-model archive per engine, which duplicates the large runtime, or bundling the worker in the base app, which enlarges every initial download. Neither is preferred.

GitHub release asset size limits must be checked against the real packaged runtime. If needed, split an archive into verified numbered parts and stream them into one staging archive. Never silently omit runtime dependencies to meet the limit.

## Local installation

Store downloads in the user's Piper data directory, outside the installed application, so they survive application updates. Reuse the shared worker and `models/nano` / `models/turbo` layout already supported by the app. Preserve discovery of existing shared and legacy installations.

Download and extract into a temporary staging directory. Verify catalog digests, safe archive paths and pinned model files before activation. Failed, cancelled or incomplete downloads must not be treated as installed and must not damage an existing usable engine. Serialize installation changes and preserve the other engine when adding a model. Keep manifest inventory checks consistent with the existing shared payload inspector.

An installed engine's readiness comes from local files and validation, without querying GitHub. Offline startup and synthesis must use those local files exclusively.

## Release and verification

Prepare version 1.10.0, following the latest published version 1.9.0. Build the shared worker once, stage both pinned model sets, produce separate download assets and their catalog, then build the Piper app and installer with its default voice. Check generated artifacts before publishing the new release from this branch.

Tests cover missing/installed engine UI states, download progress and retry, cancellation, corrupt or truncated archives, archive traversal rejection, installation of Nano followed by Turbo (and the reverse), worker reuse, preservation of existing installations, packaged default voice discovery, and network-free use after installation. Run the relevant Windows tray regression tests and packaged smoke checks. Report any unavailable hardware verification explicitly.
