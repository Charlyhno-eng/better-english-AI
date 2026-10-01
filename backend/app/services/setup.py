"""Local setup, explicit model installation and private GLM configuration."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from pydantic import SecretStr

from app.audio.parakeet import MODEL_FILE
from app.audio.pocket_tts import local_config_resources
from app.core.config import Settings

BACKEND_DIRECTORY = Path(__file__).resolve().parents[2]
KEY_FILE = BACKEND_DIRECTORY / "data" / "glm-key.json"
MODEL_IDS = ("parakeet", "pocket-tts", "openpronounce")


def saved_key(path: Path = KEY_FILE) -> SecretStr | None:
    if not path.is_file():
        return None
    key = json.loads(path.read_text(encoding="utf-8"))["api_key"]
    return SecretStr(key) if key else None


class SetupService:
    def __init__(self, settings: Settings, language_model, *, key_file: Path = KEY_FILE):
        self.settings = settings
        self.language_model = language_model
        self.key_file = key_file
        self._task: asyncio.Task | None = None
        self._states: dict[str, dict] = {}

    @property
    def pronunciation_marker(self) -> Path:
        return self.settings.audio.models_directory / "openpronounce-installed.json"

    def _installed(self, model: str) -> bool:
        if model == "parakeet":
            path = self.settings.parakeet.model_path or self.settings.audio.models_directory / MODEL_FILE
            return path.is_file() and path.stat().st_size > 0
        if model == "pocket-tts":
            directory = self.settings.audio.models_directory / "pocket-tts"
            config = self.settings.pocket_tts.config_path or directory / "config.yaml"
            voice = self.settings.pocket_tts.voice_path or directory / "alba.safetensors"
            try:
                import yaml
                local_config_resources(yaml.safe_load(config.read_text(encoding="utf-8")))
                return voice.is_file()
            except Exception:
                # A partially written or invalid YAML file is not installed.
                return False
        return self.pronunciation_marker.is_file()

    def status(self) -> dict:
        key = self.settings.glm.api_key
        return {
            "glm_configured": bool(key and key.get_secret_value().strip()),
            "models": [{"id": model, **self._states.get(model, {
                "state": "installed" if self._installed(model) else "not_installed",
                "message": "",
            })} for model in MODEL_IDS],
        }

    def save_key(self, key: SecretStr) -> None:
        value = key.get_secret_value().strip()
        self.key_file.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replacement with owner-only permissions from creation onward.
        descriptor, name = tempfile.mkstemp(dir=self.key_file.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump({"api_key": value}, file)
            temporary.replace(self.key_file)
        finally:
            temporary.unlink(missing_ok=True)
        secret = SecretStr(value)
        self.language_model.set_api_key(secret)
        self.settings.glm.api_key = secret

    def start_install(self, model: str) -> bool:
        # Called on the event loop: reserve the slot before starting the worker.
        if self._task is not None and not self._task.done():
            return False
        self._states[model] = {"state": "installing", "message": "Downloading and preparing resources…"}
        self._task = asyncio.create_task(self._install(model))
        return True

    async def _install(self, model: str) -> None:
        try:
            await asyncio.to_thread(self._download, model)
            if not self._installed(model):
                raise RuntimeError("Installation resources are incomplete")
            self._states[model] = {"state": "installed", "message": "Installation complete."}
        except Exception:
            # Download exceptions may contain private URLs/credentials.
            self._states[model] = {
                "state": "failed",
                "message": "Installation failed. Check your internet connection and free disk space, then retry. If dependencies are missing, rerun the initial installation.",
            }

    def _download(self, model: str) -> None:
        if model == "parakeet":
            from app.audio.download_parakeet import install
            install(self.settings)
        elif model == "pocket-tts":
            from app.audio.download_pocket_tts import install
            install(self.settings)
        else:
            subprocess.run(
                [sys.executable, "-m", "app.audio.download_openpronounce"],
                cwd=BACKEND_DIRECTORY, check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self.pronunciation_marker.parent.mkdir(parents=True, exist_ok=True)
            self.pronunciation_marker.write_text('{"version":"0.3.0"}', encoding="utf-8")

    async def close(self) -> None:
        # Downloads in worker threads must finish before application shutdown.
        if self._task is not None:
            await self._task
