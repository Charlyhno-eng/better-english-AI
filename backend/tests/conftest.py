import pytest


@pytest.fixture(autouse=True)
def disable_real_model_preloading(monkeypatch):
    # Unit/API tests use fake inference resources. Warmup is tested explicitly
    # with injected providers; do not load multi-GB installed models here.
    monkeypatch.setenv("BETTER_ENGLISH_AUDIO__PRELOAD_MODELS", "false")
