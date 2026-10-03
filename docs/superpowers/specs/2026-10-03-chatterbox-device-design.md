# Chatterbox device selection

Approved design: show CPU/GPU radio controls only for Chatterbox Nano. Persist
`chatterbox_device` as `cpu` or `cuda`, defaulting old settings to CPU. Keep the
preference when switching engines and when CUDA is unavailable.

Pass the requested device to the isolated worker. Resolve CUDA availability in
that environment, load Chatterbox and its inference tensors on the resolved
device, and report the effective device and a clear CPU fallback message.
Changing device prepares a replacement worker outside the controller lock before
saving settings and committing it. Existing rollback and cancellation apply.
Display fallback status in settings and a tray notification, including startup.

Verify settings round trips, default migration, device changes, rollback,
worker CUDA loading and fallback, and existing tray behavior. Real GPU inference
requires a CUDA-enabled worker Torch build and available NVIDIA hardware.
