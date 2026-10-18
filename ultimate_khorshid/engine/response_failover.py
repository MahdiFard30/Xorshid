"""Ordered response failover at the model-call boundary; never replay tools."""
import copy
import logging

from ultimate_khorshid.core.control import check_cancelled
from ultimate_khorshid.engine.base import InferenceEngine, EngineConnectionError

logger = logging.getLogger(__name__)


def retryable(exc):
    """Availability failures may switch providers; explicit policy blocks stop."""
    text = str(exc).lower()
    return not any(word in text for word in ('بلاک', 'blocked', 'safety', 'promptfeedback'))


class ResponseFailover(InferenceEngine):
    engine_id = 'response_failover'
    supports_streaming = True

    def __init__(self, primary, cfg, cloud=None, cloud_model=''):
        self.primary, self.cfg = primary, cfg
        self.cloud, self.cloud_model = cloud, cloud_model
        self.local = None
        self.mock = None
        self.last_engine = primary.engine_id
        self.last_model = ''

    def _providers(self, model):
        yield self.primary.engine_id, model, lambda: self.primary
        if self.cloud is None:
            from ultimate_khorshid.engine.groq import GroqEngine
            candidate = GroqEngine(api_key=self.cfg.engine.groq_api_key)
            if candidate.api_key:
                self.cloud, self.cloud_model = candidate, self.cfg.engine.groq_model
        if self.cloud is not None:
            yield self.cloud.engine_id, self.cloud_model, lambda: self.cloud
        local_model = self.cfg.engine.ollama_model
        def local():
            if self.local is None:
                from ultimate_khorshid.engine.ollama import OllamaEngine
                self.local = OllamaEngine(host=self.cfg.engine.ollama_host, timeout=60)
            return self.local
        yield 'ollama', local_model, local
        def mock():
            if self.mock is None:
                from ultimate_khorshid.engine.mock import MockEngine
                self.mock = MockEngine()
            return self.mock
        yield 'mock', 'mock/smart', mock

    def generate(self, messages, model, **kwargs):
        failures = []
        for name, selected_model, factory in self._providers(model):
            check_cancelled()
            options = copy.deepcopy(kwargs)
            if name != self.primary.engine_id:
                options.pop('real_model', None)
            try:
                engine = factory()
                answer = engine.generate(copy.deepcopy(messages), selected_model, **options)
                check_cancelled()
                if not isinstance(answer, dict) or (not answer.get('content') and not answer.get('tool_calls')):
                    raise EngineConnectionError('Empty response')
            except EngineConnectionError as exc:
                check_cancelled()
                if not retryable(exc):
                    raise
                # Do not store raw provider errors: they can contain credentials
                # or request text. Metadata only records the attempted provider.
                failures.append(name)
                logger.info('Response provider unavailable: %s', name)
                continue
            self.last_engine, self.last_model = name, selected_model
            answer = dict(answer)
            answer['provider'] = {'engine': name, 'model': selected_model,
                                  'fallback': bool(failures), 'failed_providers': list(failures)}
            return answer
        raise EngineConnectionError('هیچ‌کدام از موتورهای پاسخ در دسترس نیستند.')
