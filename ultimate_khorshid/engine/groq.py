"""GroqCloud text responses, using its dedicated key and fixed HTTPS endpoint."""
import copy
import json
from pathlib import Path
import urllib.request
import uuid

from ultimate_khorshid.core.registry import EngineRegistry
from ultimate_khorshid.engine.base import EngineConnectionError
from ultimate_khorshid.engine.openai_compat import OpenAICompatEngine

KEY_FILE = Path(__file__).resolve().parents[2] / '.groq.key'


@EngineRegistry.register('groq')
class GroqEngine(OpenAICompatEngine):
    engine_id = 'groq'

    def __init__(self, api_key='', timeout=45):
        from ultimate_khorshid.core.vault import get_secret
        # Never inherit OPENAI_API_KEY or OPENAI_BASE_URL from the parent.
        self.api_key = api_key or get_secret('GROQ_API_KEY')
        if not self.api_key and KEY_FILE.is_file():
            try:
                self.api_key = KEY_FILE.read_text(encoding='utf-8').strip()
            except (OSError, UnicodeError):
                self.api_key = ''
        self.base_url = 'https://api.groq.com/openai/v1'
        self.timeout = timeout

    def _headers(self):
        return {**super()._headers(), 'User-Agent': 'Khorshid/2.0'}

    def _payload(self, messages, model, **kwargs):
        payload = super()._payload(copy.deepcopy(messages), model, **kwargs)
        # Groq model IDs can themselves contain '/', e.g. openai/gpt-oss-120b.
        payload['model'] = model.removeprefix('groq/')
        for message in payload['messages']:
            message.pop('name', None)  # Unsupported by Groq's chat endpoint.
            for call in message.get('tool_calls') or []:
                call.pop('thought_signature', None)
                call.pop('thoughtSignature', None)
        return payload

    def _model_name(self, model):
        return model.removeprefix('groq/')

    def generate(self, messages, model, **kwargs):
        if not self.api_key:
            raise EngineConnectionError('Groq API key is not configured')
        return super().generate(messages, model, **kwargs)

    def generate_stream(self, messages, model, **kwargs):
        if not self.api_key:
            raise EngineConnectionError('Groq API key is not configured')
        yield from super().generate_stream(messages, model, **kwargs)

    def transcribe(self, path, language='fa'):
        if not self.api_key:
            raise EngineConnectionError('Groq API key is not configured')
        path = Path(path)
        if path.stat().st_size > 24 * 1024 * 1024:
            raise EngineConnectionError('Audio exceeds the configured 24 MiB upload limit')
        boundary = 'khorshid-' + uuid.uuid4().hex
        pieces = []
        for name, value in [('model','whisper-large-v3-turbo'), ('language',language),
                            ('response_format','json'), ('temperature','0')]:
            pieces.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                           f'{value}\r\n').encode())
        pieces.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                       'filename="recording.wav"\r\nContent-Type: audio/wav\r\n\r\n').encode())
        pieces.extend([path.read_bytes(), f'\r\n--{boundary}--\r\n'.encode()])
        req = urllib.request.Request(self.base_url + '/audio/transcriptions', data=b''.join(pieces),
                                     headers={**self._headers(),
                                              'Content-Type':'multipart/form-data; boundary=' + boundary})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                text = json.loads(response.read().decode('utf-8')).get('text', '')
            if not isinstance(text, str) or not text.strip():
                raise ValueError('Empty transcription')
            return text.strip()
        except Exception as exc:
            raise EngineConnectionError('Groq transcription failed') from exc
