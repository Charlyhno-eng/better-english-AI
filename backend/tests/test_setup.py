import asyncio
import json
import stat
from unittest.mock import Mock

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.ai.glm import GLMProvider
from app.core.config import Settings
from app.main import create_app
from app.services.setup import SetupService, saved_key


def service(tmp_path):
    settings = Settings(_env_file=None, audio={"models_directory": tmp_path / "models"})
    return SetupService(settings, GLMProvider(settings.glm), key_file=tmp_path / "glm-key.json")


def test_private_key_persistence_and_immediate_use(tmp_path):
    setup = service(tmp_path)
    setup.save_key(SecretStr("test-private-key"))
    assert saved_key(setup.key_file).get_secret_value() == "test-private-key"
    assert stat.S_IMODE(setup.key_file.stat().st_mode) == 0o600
    assert setup.settings.glm.api_key.get_secret_value() == "test-private-key"
    assert setup.language_model._settings.api_key.get_secret_value() == "test-private-key"
    assert "test-private-key" not in json.dumps(setup.status())
    assert setup.api_key() == "test-private-key"
    setup.save_key(SecretStr("replacement"))
    assert saved_key(setup.key_file).get_secret_value() == "replacement"


def test_application_restores_web_key_at_startup(tmp_path, monkeypatch):
    setup = service(tmp_path)
    setup.save_key(SecretStr('saved-web-key'))
    fresh_settings = Settings(_env_file=None)
    monkeypatch.setattr('app.main.Settings', lambda: fresh_settings)
    monkeypatch.setattr('app.main.saved_key', lambda: saved_key(setup.key_file))
    app = create_app()
    assert app.state.settings.glm.api_key.get_secret_value() == 'saved-web-key'
    assert app.state.setup_service.language_model._settings.api_key.get_secret_value() == 'saved-web-key'


def test_web_key_and_validation(tmp_path):
    app = create_app(Settings(_env_file=None))
    setup = service(tmp_path)
    app.state.setup_service = setup
    headers = {"Origin": "http://testserver"}
    with TestClient(app) as client:
        assert client.post("/api/setup/glm", json={"api_key": "secret"}).status_code == 403
        assert client.post("/api/setup/glm", json={"api_key": "secret"},
                           headers={"Origin": "https://untrusted.example"}).status_code == 403
        for key in ("", "   ", "private\nkey", "x" * 4097):
            response = client.post("/api/setup/glm", json={"api_key": key}, headers=headers)
            assert response.status_code == 422
            assert "private" not in response.text
        response = client.post("/api/setup/glm", json={"api_key": "private-key"}, headers=headers)
        assert response.status_code == 200
        assert "private-key" not in response.text
        response = client.get("/api/setup")
        assert response.json()["glm_configured"] is True
        key_response = client.get("/api/setup/glm")
        assert key_response.json() == {"api_key": "private-key"}
        assert key_response.headers["cache-control"] == "no-store"
        assert response.headers["cache-control"] == "no-store"
        assert "private-key" not in response.text


def test_install_lifecycle_failure_retry_and_concurrency(tmp_path):
    setup = service(tmp_path)
    started = asyncio.Event()
    release = asyncio.Event()

    async def run():
        async def download(*args):
            started.set()
            await release.wait()
            setup.pronunciation_marker.parent.mkdir(parents=True)
            setup.pronunciation_marker.write_text('{}')

        # Retain the real scheduling/state logic, replace only the heavy worker.
        from unittest.mock import patch
        with patch('app.services.setup.asyncio.to_thread', side_effect=download):
            assert setup.start_install("openpronounce")
            await started.wait()
            assert not setup.start_install("parakeet")
            assert setup.status()["models"][2]["state"] == "installing"
            release.set()
            await setup.close()
        assert setup.status()["models"][2]["state"] == "installed"
        assert service(tmp_path).status()["models"][2]["state"] == "installed"
        setup._download = Mock(side_effect=RuntimeError("private-download-url"))
        assert setup.start_install("parakeet")
        await setup.close()
        assert setup.status()["models"][0]["state"] == "failed"
        assert "private-download-url" not in json.dumps(setup.status())
        def install(model):
            (setup.settings.audio.models_directory / "parakeet-tdt-0.6b-v3.nemo").write_bytes(b"checkpoint")
        setup._download = install
        assert setup.start_install("parakeet")
        await setup.close()
        assert setup.status()["models"][0]["state"] == "installed"
    asyncio.run(run())


def test_web_install_and_unknown_model(tmp_path):
    setup = service(tmp_path)
    setup._download = Mock(side_effect=RuntimeError("private-error"))
    app = create_app(Settings(_env_file=None))
    app.state.setup_service = setup
    with TestClient(app) as client:
        assert client.post('/api/setup/models/parakeet', json={}).status_code == 403
        for origin in ('https://untrusted.example', 'http://testserver:5173'):
            for model in ('parakeet', 'openpronounce', 'pocket-tts'):
                assert client.post(f'/api/setup/models/{model}', json={},
                                   headers={"Origin": origin}).status_code == 403
        setup._download.assert_not_called()
        headers = {"Origin": "http://testserver"}
        assert client.post('/api/setup/models/unknown', json={}, headers=headers).status_code == 422
        response = client.post('/api/setup/models/parakeet', json={}, headers=headers)
        assert response.status_code == 202
        assert response.json() == {"state": "installing"}
    assert setup.status()["models"][0]["state"] == "failed"


def test_downloads_reuse_existing_installers(tmp_path, monkeypatch):
    setup = service(tmp_path)
    parakeet = Mock()
    pocket = Mock()
    process = Mock()
    monkeypatch.setattr('app.audio.download_parakeet.install', parakeet)
    monkeypatch.setattr('app.audio.download_pocket_tts.install', pocket)
    monkeypatch.setattr('app.services.setup.subprocess.run', process)
    setup._download('parakeet')
    setup._download('pocket-tts')
    setup._download('openpronounce')
    parakeet.assert_called_once_with(setup.settings)
    pocket.assert_called_once_with(setup.settings)
    assert process.call_args.kwargs['check'] is True
    assert process.call_args.args[0][-1] == 'app.audio.download_openpronounce'
    assert setup.pronunciation_marker.is_file()


def test_pocket_status_requires_all_resources(tmp_path):
    import sys
    from types import SimpleNamespace
    from unittest.mock import patch
    setup = service(tmp_path)
    directory = setup.settings.audio.models_directory / 'pocket-tts'
    directory.mkdir(parents=True)
    config = {"weights_path": str(directory / 'weights'), "flow_lm": {"lookup_table": {"tokenizer_path": str(directory / 'tokenizer')}}}
    (directory / 'config.yaml').write_text(json.dumps(config))
    (directory / 'alba.safetensors').write_bytes(b'voice')
    with patch.dict(sys.modules, {'yaml': SimpleNamespace(safe_load=json.loads)}):
        assert not setup._installed('pocket-tts')
        (directory / 'weights').write_bytes(b'weights')
        (directory / 'tokenizer').write_bytes(b'tokenizer')
        assert setup._installed('pocket-tts')
