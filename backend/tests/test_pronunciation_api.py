import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.core.config import Settings
from app.audio.contracts import PronunciationAssessment
from app.core.errors import ProviderUnavailableError
from test_transcription import recording


def setup():
    app = create_app(Settings(_env_file=None))
    service = SimpleNamespace(analyze=AsyncMock(return_value=PronunciationAssessment(())))
    app.state.pronunciation_service = service
    payload = {"audio_base64": base64.b64encode(recording().content).decode(),
               "reference_text": "Three things."}
    return app, service, payload


def test_direct_analysis_without_conversation():
    app, service, payload = setup()
    app.state.conversation_service.respond = AsyncMock(side_effect=AssertionError("No conversation"))
    with TestClient(app) as client:
        response = client.post('/api/pronunciation/analyze', json=payload)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['errors'] == []
    assert service.analyze.await_args.args[1] == 'Three things.'
    assert service.analyze.await_args.args[0].content == recording().content


@pytest.mark.parametrize('change,status', [({'audio_base64': '!'}, 400),
                                         ({'reference_text': None}, 422)])
def test_bad_input(change, status):
    app, service, payload = setup()
    with TestClient(app) as client:
        response = client.post('/api/pronunciation/analyze', json=payload | change)
    assert response.status_code == status
    service.analyze.assert_not_awaited()


def test_safe_unavailable():
    app, service, payload = setup()
    service.analyze.side_effect = ProviderUnavailableError('Analysis unavailable.')
    with TestClient(app) as client:
        response = client.post('/api/pronunciation/analyze', json=payload)
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'provider_unavailable'
