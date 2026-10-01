"""Explicit installation of English model, tokenizer and Alba voice."""

import shutil
from pathlib import Path

from app.core.config import Settings

VOICE_REPOSITORY = "kyutai/pocket-tts-without-voice-cloning"
VOICE_REVISION = "e81d79e8194ad4c7ce879c87a4258ef20cbf2487"


def download_resource(uri: str, destination: Path) -> Path:
    from huggingface_hub import hf_hub_download

    if not uri.startswith("hf://"):
        raise ValueError("Expected a Hugging Face model resource")
    resource, revision = uri[5:].rsplit("@", 1)
    owner, repository, filename = resource.split("/", 2)
    return Path(hf_hub_download(
        repo_id=f"{owner}/{repository}", filename=filename,
        revision=revision, local_dir=destination,
    )).resolve()


def install(settings: Settings) -> None:
    import pocket_tts
    import yaml
    from huggingface_hub import hf_hub_download

    directory = (settings.audio.models_directory / "pocket-tts").resolve()
    directory.mkdir(parents=True, exist_ok=True)
    source = Path(pocket_tts.__file__).resolve().parent / "config" / "english.yaml"
    config = yaml.safe_load(source.read_text(encoding="utf-8"))
    weights = download_resource(config["weights_path_without_voice_cloning"], directory)
    tokenizer = download_resource(config["flow_lm"]["lookup_table"]["tokenizer_path"], directory)
    config["weights_path"] = config["weights_path_without_voice_cloning"] = str(weights)
    config["flow_lm"]["lookup_table"]["tokenizer_path"] = str(tokenizer)
    voice = Path(hf_hub_download(
        repo_id=VOICE_REPOSITORY, filename="languages/english/embeddings/alba.safetensors",
        revision=VOICE_REVISION, local_dir=directory,
    ))
    voice_path = (settings.pocket_tts.voice_path or directory / "alba.safetensors").resolve()
    if voice.resolve() != voice_path:
        voice_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(voice, voice_path)
    config_path = settings.pocket_tts.config_path or directory / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    print(f"Pocket TTS installed: {config_path}, voice: {voice_path}")


def main() -> None:
    install(Settings())


if __name__ == "__main__":
    main()
