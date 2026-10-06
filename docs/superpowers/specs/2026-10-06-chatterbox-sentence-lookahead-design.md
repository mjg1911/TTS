# Chatterbox Sentence Look-Ahead Design

## Context

`SpeechWorker` splits text into sentences for non-Piper backends, but currently requests each sentence only after the preceding sentence's audio has finished playing. The serial synthesis/playback loop can leave an audible gap at each sentence boundary. Chatterbox Nano and Turbo use this non-Piper path.

Piper follows a separate streaming path. It has its own sentence streaming setting and configurable inter-sentence pause, which must remain unchanged.

## Goal

Reduce gaps between sentences for non-Piper speech backends by synthesizing one sentence ahead while the current sentence plays. Keep sentence order, backend protocol and response validation, cancellation, error reporting, and worker shutdown behavior intact.

## Scope

- Apply look-ahead to non-Piper backends routed through `SpeechWorker`, including Chatterbox Nano and Turbo.
- Continue to use the existing sentence splitter and pass each sentence to the backend in source order.
- Leave Piper synthesis, its streaming setting, and its configured pause unchanged.
- Do not add a fixed pause or a user-facing setting.

## Chosen design

Use one producer thread per active non-Piper request and the existing speech-worker thread as the playback consumer. The producer requests and fully drains one sentence at a time from the backend. It concatenates that sentence's PCM chunks into one byte buffer and places a completed sentence item on a bounded queue. The consumer removes sentence items in order and sends them to the existing playback pipeline.

The producer starts with the first sentence and queues its completed audio. For each later sentence, it reserves the sole look-ahead slot before synthesis begins. The consumer releases that reservation when it takes the sentence for playback. This permits the producer to synthesize the next sentence while the current one is playing, while preventing an in-progress sentence buffer from sitting outside a full queue. Use a capacity-one queue and cancellation-aware timed waits for both slot reservation and queue operations. Backend inference stays sequential; only synthesis and playback overlap.

Keep the backend interface unchanged. Obtain the first synthesis result before creating the playback pipeline, as the current streamed path does, and use its sample rate for the player. Hand its chunk iterator and the remaining sentences to the producer. The producer validates each later result against that initial sample rate. Do not alter worker framing or response checks.

## Request lifecycle and errors

`SpeechWorker._speak` remains responsible for the request's start and terminal events, playback object, backend lease, and final logging. The producer communicates sentence audio, end-of-stream, or the original synthesis exception through the queue. The consumer re-raises a producer exception in the synthesis phase so existing synthesis failure reporting remains in effect. Exceptions raised while playing remain playback failures.

The producer must stop when the request is cancelled, the worker shuts down, playback fails, or the consumer exits. Queue reads, writes, and look-ahead slot reservations must use bounded waits that check stop/cancellation state; neither side may wait forever on an empty or full queue. Cleanup must wake blocked queue operations, close any abandoned backend chunk iterator, and finish producer cleanup before releasing the backend lease. Discard buffered future audio after cancellation and emit only the existing terminal event for the request.

Measure synthesis time around backend work in the producer. Waiting for queue capacity or for the consumer must not be counted as model synthesis time. Preserve the existing request generation, response checks, and failure phase in logs and events.

## Compatibility

- Piper continues to use its current direct or sentence-streaming synthesis path, including the live sentence-pause setting.
- Non-Piper sentences remain in source order and retain the same text and punctuation boundaries.
- The backend sees one active synthesis request at a time; this design does not run parallel model inference.
- At most one future sentence is being synthesized or held for playback at a time; the producer reserves the look-ahead slot before assembling its PCM buffer.
- Audio playback continues through the existing playback pipeline, preserving speed, pitch, pause/resume, and stop behavior.

## Verification criteria

- With playback of sentence one held open, synthesis of sentence two begins before sentence one's playback completes.
- Audio is played in source order, with no additional fixed pause between non-Piper sentences.
- The producer does not begin another synthesis while its single look-ahead slot is occupied by a future sentence being synthesized or waiting in the queue.
- A sample-rate mismatch and a backend synthesis error surface through the existing synthesis failure path; a player error remains a playback failure.
- Cancellation during synthesis, queue backpressure, or playback stops further synthesis, releases the backend lease, and does not strand either side waiting on the queue.
- Piper audio, configured sentence pauses, and existing Piper streaming behavior remain unchanged.