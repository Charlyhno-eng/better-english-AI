"""Prepare pronunciation resources in an isolated CPU process after a UI action."""
import os
import tempfile
from pathlib import Path


def main() -> None:
    os.environ["OPENPRONOUNCE_DEVICE"] = "cpu"
    os.environ["OPENPRONOUNCE_TTS"] = "piper"
    os.environ["OPENPRONOUNCE_PHONEME_MODEL"] = "facebook/wav2vec2-lv-60-espeak-cv-ft"
    import torch
    import openpronounce
    from openpronounce.device import get_device

    if get_device().type != "cpu":
        raise RuntimeError("Pronunciation setup requires CPU")
    torch.set_num_threads(2)
    # Use synthetic speech to exercise the public API and fetch every required
    # checkpoint/voice without storing any learner recording or loading GLM.
    with tempfile.TemporaryDirectory() as directory:
        text = "Hello, how are you?"
        audio = openpronounce.text2speech(text, filename=str(Path(directory) / "reference.wav"))
        openpronounce.compare_audio_with_text(
            openpronounce.load_audio(audio), text, use_phone_model=True, lang="en",
        )


if __name__ == "__main__":
    main()
