"""Explicit model installation; inference itself never downloads a checkpoint."""

from pathlib import Path

from app.audio.parakeet import MODEL_FILE, REPOSITORY
from app.core.config import Settings


def install(settings: Settings) -> None:
    from huggingface_hub import hf_hub_download

    destination = settings.parakeet.model_path or settings.audio.models_directory / MODEL_FILE
    destination.parent.mkdir(parents=True, exist_ok=True)
    downloaded = hf_hub_download(
        repo_id=REPOSITORY, filename=MODEL_FILE, local_dir=destination.parent,
    )
    if destination.name != MODEL_FILE:
        Path(downloaded).replace(destination)
    print(f"Parakeet checkpoint installed at {destination}")


def main() -> None:
    install(Settings())


if __name__ == "__main__":
    main()
