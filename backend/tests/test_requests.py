import base64

import pytest

from app.api.requests import decode_audio
from app.core.errors import InvalidAudioError


def test_decoded_limit_is_enforced_even_when_base64_lengths_match():
    # One and three bytes both encode to four characters.
    assert decode_audio(base64.b64encode(b'a').decode(), 'audio/wav', 1).content == b'a'
    with pytest.raises(InvalidAudioError, match='size limit'):
        decode_audio(base64.b64encode(b'abc').decode(), 'audio/wav', 1)
