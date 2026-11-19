"""Small standard-library client for the local Ollama HTTP API.

The project intentionally avoids a Python SDK dependency. Ollama is an external
free runtime and all traffic stays on the configured local endpoint.
"""

from __future__ import annotations

import json
import logging
import socket
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)


class OllamaError(Exception):
    """Raised when the local model is disabled, unavailable, or malformed."""


def ollama_enabled() -> bool:
    return bool(
        getattr(settings, 'OLLAMA_ENABLED', True)
        and (getattr(settings, 'OLLAMA_BASE_URL', '') or '').strip()
        and (getattr(settings, 'OLLAMA_MODEL', '') or '').strip()
    )


def _request_chat(payload):
    base_url = (getattr(settings, 'OLLAMA_BASE_URL', '') or '').strip().rstrip('/')
    if not base_url:
        raise OllamaError('The local AI endpoint is not configured.')

    request = urllib.request.Request(
        f'{base_url}/api/chat',
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'Accept': 'application/json',
            'User-Agent': 'EuphoriaDJ-Local-Assistant/1.0',
        },
        method='POST',
    )

    # Ignore system HTTP proxies for the local endpoint.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=getattr(settings, 'OLLAMA_TIMEOUT', 60)) as response:
            body = response.read().decode('utf-8')
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError, ValueError) as exc:
        logger.warning('Local Ollama request failed: %s', type(exc).__name__)
        raise OllamaError('The local AI model is unavailable.') from exc

    try:
        parsed = json.loads(body)
    except (TypeError, ValueError) as exc:
        logger.warning('Local Ollama returned invalid JSON.')
        raise OllamaError('The local AI model returned an invalid response.') from exc

    if not isinstance(parsed, dict):
        logger.warning('Local Ollama returned a non-object JSON response.')
        raise OllamaError('The local AI model returned an invalid response.')
    message = parsed.get('message')
    content = message.get('content') if isinstance(message, dict) else ''
    if not isinstance(content, str):
        content = ''
    content = content.strip()
    if not content:
        logger.warning('Local Ollama returned an empty message.')
        raise OllamaError('The local AI model returned an empty response.')
    return content


def chat(messages, *, json_format=False, temperature=0.1, num_predict=None):
    """Send a chat request to Ollama and return the assistant text."""
    if not ollama_enabled():
        raise OllamaError('The local AI assistant is disabled.')

    payload = {
        'model': settings.OLLAMA_MODEL,
        'messages': messages,
        'stream': False,
        'options': {
            'temperature': temperature,
            'num_predict': num_predict or getattr(settings, 'OLLAMA_MAX_PREDICT', 220),
            'num_ctx': getattr(settings, 'OLLAMA_NUM_CTX', 3072),
        },
    }
    if json_format:
        payload['format'] = 'json'

    return _request_chat(payload)
