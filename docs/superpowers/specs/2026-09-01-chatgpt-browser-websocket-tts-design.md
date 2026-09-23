# ChatGPT Browser WebSocket TTS Design

## Status

Approved design specification. This document describes the intended feature
and its user-visible behavior. It contains no implementation code.

## Goal

Allow Piper Tray to read ChatGPT responses from a supported desktop browser
while ChatGPT is still generating the response.

When ChatGPT produces the first complete sentence, Piper should be able to
start speaking it immediately. Later sentences should be spoken in their
original order as they become available.

The feature must preserve Piper's existing local voice, playback, cancellation,
and speech-priority behavior.

## Scope

The feature consists of two cooperating components:

1. A browser extension that observes the ChatGPT web page and sends complete
   sentences.
2. Piper Tray, which receives those sentences through a local WebSocket
   connection and manages their playback.

The browser extension is responsible for detecting and transmitting text. It
must not perform text-to-speech.

Piper remains responsible for the speech queue, voice configuration, playback,
cancellation, prioritization, connection security, and local diagnostics.

The first supported browser target is a Chromium-based desktop browser, such
as Chrome or Edge, running ChatGPT in its normal web interface.

The Downloads-folder JSON approach may be used for an early prototype, but it
is not the target transport for the completed feature.

## User experience

The user enables browser ChatGPT speech from Piper Tray. When enabled and the
browser extension is connected:

1. The user submits a message in ChatGPT.
2. ChatGPT begins streaming its response.
3. The extension detects the first complete sentence.
4. The extension sends that sentence to Piper.
5. Piper places the sentence in the browser-speech queue.
6. Piper starts speaking it as soon as speech resources are available.
7. Subsequent sentences are added to the queue and spoken in order.

The user should not need to manually select text, copy text, or manage files.

The feature should have a clear enabled/disabled state and should expose enough
status information for the user to understand whether the browser is connected
and whether sentences are waiting to be spoken.

## Architecture

The intended data flow is:

    ChatGPT web page
        -> browser extension
        -> local WebSocket connection
        -> Piper browser-message receiver
        -> browser sentence queue
        -> existing Piper speech system

The browser extension and Piper must communicate through a narrow message
interface. The receiver must not be coupled to the details of the ChatGPT page
layout or the extension's internal DOM-observation logic.

The browser sentence queue must be separate from Piper's application-command
queue. Application commands coordinate events such as hotkeys and tray actions;
the browser sentence queue represents ordered speech work and has different
cancellation and overflow behavior.

## Browser extension responsibilities

The extension should:

- operate only on the supported ChatGPT web interface;
- observe response text as it streams;
- determine when a sentence is complete enough to send;
- preserve sentence order;
- associate each sentence with its conversation and response;
- avoid sending the same sentence more than once;
- avoid sending incomplete, empty, or non-response page text;
- send sentences over the local WebSocket connection;
- reconnect when Piper is restarted or temporarily unavailable;
- stop sending when the feature is disabled or the connection is closed.

The extension should be defensive about changes in the ChatGPT page. It must
not assume that one particular visual element or CSS class will remain stable
forever.

The extension should not transmit account credentials, cookies, page history,
or unrelated page content. It should send only the minimum sentence metadata
and text needed by Piper.

The extension may observe only ChatGPT response content on the allowed ChatGPT
site. It must not observe or collect other tabs, browsing history, cookies,
prompts from unrelated pages, or content from unrelated websites.

## Piper responsibilities

Piper should:

- start and stop the local WebSocket receiver with the application lifecycle;
- accept only authenticated local connections;
- validate every incoming message;
- reject malformed, oversized, duplicated, or out-of-order messages as
  appropriate;
- identify the current browser response and sentence sequence;
- place accepted sentences into the browser-speech queue;
- pass speech requests through Piper's existing preparation and playback path;
- expose connection and queue status to the tray UI;
- cancel browser speech when required by existing Piper controls;
- clear stale browser speech when a new response begins or the feature is
  disabled.

The WebSocket receiver must not directly control audio playback. It should
hand validated speech work to the part of Piper that already handles voices,
workers, cancellation, and speech events.

## Protocol messages

Every WebSocket message must include a protocol version. The first protocol
version should define at least these message types:

- `response_start`: identifies the beginning of a new ChatGPT response and
  establishes the response identity and starting sequence.
- `sentence`: carries one complete sentence, its response identity, and its
  sequence number.
- `response_end`: identifies that ChatGPT has finished the response and carries
  the response identity so Piper can close or reconcile the response state.

Messages should also include enough information for Piper to reject stale
responses, detect duplicates, and recognize a protocol mismatch. A reconnect
must not cause previously accepted sentences to be spoken again. Piper should
discard unsupported protocol versions safely and report the integration as
unavailable without affecting normal Piper operation.

## Sentence and response behavior

The extension should send a sentence only after it reaches a stable boundary,
normally punctuation such as a period, question mark, or exclamation mark.
The design must account for the fact that streamed text can still be revised
or extended before the response is complete.

Each sentence should carry enough identity to distinguish it from other
sentences. The identity should include, conceptually:

- conversation identity;
- response or turn identity;
- sentence sequence number;
- sentence text.

Piper should treat the response identity and sequence number as more important
than the text itself when preventing duplicates.

When a new response is detected, sentences belonging to an older response
should not continue indefinitely. Piper should finish the sentence currently
being spoken, discard the remaining queued sentences from the older response,
and then switch to the new response. If no sentence is currently being spoken,
the remaining old queue should be discarded immediately.

If ChatGPT produces a response that contains no usable sentence, Piper should
remain available for later responses without reporting a playback failure.

## Queue behavior

The queue should be FIFO within one response. Piper should begin with the first
accepted sentence instead of waiting for the entire response.

The queue should not become an unbounded backlog. It should have a defined
maximum size or response-level replacement policy so that a delayed or broken
connection cannot cause Piper to read stale content long after the user has
moved on.

The queue should support:

- adding a sentence;
- reporting its size and current sentence;
- removing the next sentence for playback;
- clearing the current browser response;
- cancelling all browser speech;
- discarding stale responses;
- safely handling duplicates and reconnects.

## Speech priority

Browser ChatGPT speech should be treated as automatic, lower-priority speech.
The existing user-requested actions retain priority over it.

The intended priority order is:

1. User-selected text speech.
2. Error feedback speech.
3. Browser ChatGPT response speech.
4. Launch or welcome speech.

Starting selected-text speech should stop or supersede browser response speech
according to Piper's existing behavior. F8 and the existing Stop Speaking
command should stop current browser speech. Stopping speech should not
necessarily disable the browser connection or the feature itself; later
sentences may still be accepted unless the user disables browser speech.

The final implementation must explicitly define whether sentences arriving
while higher-priority speech is active are queued, skipped, or cause the
browser response queue to be cleared. The preferred behavior is to avoid an
unexpected stale backlog.

## Connection lifecycle

When browser speech is enabled, Piper should start listening for the extension.
When it is disabled, Piper should stop accepting browser messages and clear
browser-specific queued and active speech.

If Piper starts before the extension, it should wait for a connection. If the
extension starts before Piper, it should retry without requiring the user to
reload the ChatGPT page.

If the connection is interrupted:

- current Piper speech should follow normal cancellation behavior;
- Piper should report that the browser connection is unavailable;
- the extension should retry with controlled backoff;
- Piper should not replay old sentences merely because the connection returns;
- duplicate messages received after reconnect should be ignored.

On application shutdown, Piper must close the receiver, stop browser speech,
and release the local listener cleanly.

## Security and privacy

The WebSocket receiver must listen only on the local machine. It must not be
reachable from the local network or the public internet.

Connections must require a private authentication token or equivalent
handshake secret. The token should be generated or provisioned locally and
must not be displayed in logs or sent to a remote service.

Piper should validate:

- message structure;
- message type;
- text size;
- response and sentence identifiers;
- connection rate and queue limits.

The system must not transmit ChatGPT cookies, credentials, authorization
headers, or unrelated browser data. Response text should remain local and
should not be written to Piper settings or normal diagnostic logs.

The extension should request the narrowest browser permissions that support
the feature and must be restricted to the supported ChatGPT origin. It must
not request permission to read or modify unrelated websites unless support for
those sites is explicitly added in a future version.

## Failure handling

The feature must fail independently of Piper's core operation. If the browser
extension is missing, disconnected, incompatible, or malfunctioning, Piper
must still start and continue to support normal selected-text speech.

The following conditions should be handled without crashing Piper:

- no browser extension is connected;
- the WebSocket connection closes unexpectedly;
- a message is malformed;
- a message is too large;
- sentences arrive out of order;
- the same sentence arrives more than once;
- a response is revised during streaming;
- the browser sends a stale response after reconnecting;
- the queue reaches its configured limit;
- speech synthesis or playback fails;
- Piper is disabled while sentences are queued.

User-facing status should describe the category of the problem without
revealing response text or security-sensitive details.

## Settings and status

Piper should provide a setting to enable or disable browser ChatGPT speech.
The feature should default to disabled until the behavior has been validated.

The tray UI should be able to communicate at least:

- browser speech disabled;
- waiting for browser connection;
- browser connected;
- browser connected with queued sentences;
- browser connection temporarily unavailable;
- browser integration unavailable because the message format is unsupported.

The user should have a way to stop current browser speech and clear its queue
without affecting unrelated Piper settings.

## Testing and acceptance criteria

The feature is acceptable when the following outcomes are demonstrated:

- Piper can start and stop its local browser receiver cleanly.
- The extension can connect using the configured local authentication.
- A complete first sentence starts speaking before the full response finishes.
- Later sentences are spoken in the correct order.
- A sentence is not spoken twice because of DOM updates or reconnection.
- Incomplete and empty text is not spoken.
- A new response does not inherit stale sentences from an older response.
- Queue limits prevent an unbounded backlog.
- F8 and Stop Speaking cancel active browser speech correctly.
- Selected-text speech retains priority over browser speech.
- Disabling browser speech stops its receiver and clears browser speech state.
- Restarting Piper does not unexpectedly replay old browser sentences.
- Piper remains usable when the extension is absent or unavailable.
- Invalid, oversized, or unauthenticated messages are rejected safely.
- Browser response text does not appear in Piper settings or logs.

Testing should cover the receiver, message validation, connection lifecycle,
queue behavior, duplicate handling, response replacement, speech-priority
interaction, shutdown, and recovery after interruption.

## Out of scope

This feature does not attempt to:

- replace ChatGPT's own Voice feature;
- create a new ChatGPT client;
- send messages to ChatGPT;
- upload browser content to a cloud TTS service;
- monitor arbitrary websites in the first version;
- expose Piper's WebSocket receiver outside the local computer;
- preserve and replay an unlimited history of missed responses.

## Open decisions for implementation planning

The implementation plan should make the following decisions explicitly before
development begins:

1. The exact sentence-boundary and revision rules used by the extension.
2. Any protocol fields beyond `response_start`, `sentence`, and `response_end`,
   while preserving explicit protocol versioning.
3. The authentication-token creation and storage flow.
4. The maximum sentence and queue sizes.
5. The exact policy for sentences arriving during higher-priority speech.
6. The supported browser packaging and installation workflow.
