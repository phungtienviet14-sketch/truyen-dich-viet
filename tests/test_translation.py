import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app.translator.deepseek import DeepSeekTranslator


def mock_provider(monkeypatch, payload, status=200):
    requests = []

    async def post(client, url, **kwargs):
        requests.append(kwargs["json"])
        return httpx.Response(status, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    return requests


def completion(content="Chương 1\n\nĐây là bản dịch đầy đủ.", reason="stop"):
    return {"id": "test-request", "model": "deepseek-v4-flash", "choices": [
        {"finish_reason": reason, "message": {"content": content}}
    ], "usage": {"prompt_tokens": 20, "completion_tokens": 12, "total_tokens": 32}}


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,content", [("length", "Bị cắt"), ("stop", " "),
                                           ("content_filter", "Bị chặn")])
async def test_incomplete_provider_output_is_rejected(monkeypatch, reason, content):
    mock_provider(monkeypatch, completion(content, reason))
    with pytest.raises(ValueError):
        await DeepSeekTranslator(api_key="test-key")._call_api([])


@pytest.mark.asyncio
async def test_v4_flash_request_and_usage(monkeypatch):
    requests = mock_provider(monkeypatch, completion())
    result = await DeepSeekTranslator(api_key="test-key", model="deepseek-v4-flash")._call_api([])
    assert requests[0]["thinking"] == {"type": "disabled"}
    assert requests[0]["max_tokens"] > 0
    assert result.prompt_tokens == 20
    assert result.completion_tokens == 12


@pytest.mark.asyncio
async def test_unauthorized_is_not_retried(monkeypatch):
    requests = mock_provider(monkeypatch, {"error": "bad credentials"}, 401)
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    with pytest.raises(httpx.HTTPStatusError):
        await DeepSeekTranslator(api_key="test-key")._call_api([])
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_retry_transient_failure(monkeypatch):
    requests = mock_provider(monkeypatch, {"error": "busy"}, 503)
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    with pytest.raises(httpx.HTTPStatusError):
        await DeepSeekTranslator(api_key="test-key")._call_api([])
    assert len(requests) == 3


def test_split_long_single_paragraph_without_losing_text():
    from app.translator.deepseek import split_text
    source = "长" * 10000
    parts = split_text(source)
    assert max(map(len, parts)) <= 3500
    assert "".join(parts) == source


@pytest.mark.asyncio
async def test_invalid_schema_is_actionable(monkeypatch):
    mock_provider(monkeypatch, {"choices": []})
    with pytest.raises(ValueError, match="DeepSeek"):
        await DeepSeekTranslator(api_key="test-key")._call_api([])


def test_quality_checks_detect_missing_glossary_and_chinese_output():
    from app.translator.deepseek import quality_issues
    assert quality_issues("张三走出城。", "张三走出城。", [])
    assert quality_issues("张三走出城。", "Một người bước ra khỏi thành.", [
        {"original_term": "张三", "translated_term": "Trương Tam"}
    ])
