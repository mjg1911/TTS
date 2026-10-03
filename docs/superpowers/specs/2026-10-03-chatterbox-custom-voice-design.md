# Chatterbox custom voice

Approved by the user on 2026-10-03: add Import reference clip, display the imported filename, and a Use custom voice toggle to Chatterbox options. Copy imported clips into Piper's local data folder and persist the clip and toggle across restarts. Turning the toggle off restores the bundled default voice. Validate before saving; invalid imports preserve the working voice.

Use a local managed copy rather than a link to the original, so moving the source does not break the voice. A voice library is outside this request; one reference clip is sufficient. Reference clips must exceed five seconds, as required by the pinned model. Support WAV initially with a clear file picker and instructions, allowing standard-library validation without new tray dependencies.

Prepare reference conditionals once during background worker readiness. Every worker begins with the default conditionals and optionally replaces them from a reference. Replacing a clip or changing the toggle must prepare a new candidate before committing settings, preserving the existing transactional backend swap and cancellation behavior. Persist the inactive clip when default voice is selected.

Tests cover managed-copy validation, backward-compatible settings, custom initialization, default restoration, background apply and rollback, startup restoration, and visible options controls. Stay on the Chatterbox branch and create a feature commit after verification.
