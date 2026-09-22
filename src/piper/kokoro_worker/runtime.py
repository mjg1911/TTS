from __future__ import annotations

from .audio import float_audio_to_pcm16


class KokoroRuntime:
    sample_rate = 24000

    def __init__(self, config_path, model_path, voices):
        self._config_path = config_path
        self._model_path = model_path
        self._voices = voices
        self._model = None
        self._pipelines = {}
        self._voice_cache = {}

    def load(self):
        import os

        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from spacy import cli as spacy_cli

        def blocked_spacy_download(*_args, **_kwargs):
            raise RuntimeError("runtime spaCy downloads are disabled")

        spacy_cli.download = blocked_spacy_download
        from kokoro import KModel

        self._model = KModel(
            config=str(self._config_path),
            model=str(self._model_path),
        ).to("cpu").eval()

    def synthesize_segments(self, text, voice_id):
        if self._model is None:
            self.load()
        asset = self._voices[voice_id]
        voice = self._voice_cache.get(voice_id)
        if voice is None:
            import torch

            voice = torch.load(
                str(asset.path),
                map_location="cpu",
                weights_only=True,
            )
            self._voice_cache[voice_id] = voice

        pipeline = self._pipelines.get(asset.language)
        if pipeline is None:
            from kokoro import KPipeline

            pipeline = KPipeline(
                lang_code=asset.language,
                model=self._model,
                device="cpu",
            )
            if asset.language in {"a", "b"} and getattr(
                getattr(pipeline, "g2p", None), "fallback", None
            ) is None:
                raise RuntimeError("espeak-ng fallback is required for Kokoro English")
            self._pipelines[asset.language] = pipeline

        for _graphemes, _phonemes, waveform in pipeline(
            text,
            voice=voice,
            speed=1,
        ):
            yield float_audio_to_pcm16(waveform)
