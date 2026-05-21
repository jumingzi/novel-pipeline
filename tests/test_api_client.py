import json
import pytest
import httpx
from pipeline.api_client import DeepSeekClient, fix_json_output


class FakeResponse:
    def __init__(self, content, status_code=200):
        self._content = content
        self.status_code = status_code

    def json(self):
        return json.loads(self._content)


class FakeAsyncClient:
    def __init__(self, responses):
        self.responses = responses
        self.call_count = 0

    async def post(self, url, json=None, headers=None, timeout=None):
        resp = self.responses[self.call_count]
        self.call_count += 1
        return resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def aclose(self):
        pass


# --- fix_json_output tests ---

def test_fix_json_removes_markdown_fence():
    result = fix_json_output('```json\n{"a": 1}\n```')
    assert result == '{"a": 1}'


def test_fix_json_removes_thinking_prefix():
    result = fix_json_output('Some thinking text...\n{"result": "ok"}')
    assert result == '{"result": "ok"}'


def test_fix_json_valid_json_unchanged():
    result = fix_json_output('{"key": "value"}')
    assert result == '{"key": "value"}'


def test_fix_json_extracts_object_from_wrapper():
    result = fix_json_output('Here is the analysis:\n{"characters": [{"name": "A"}]}\nEnd.')
    assert '"characters"' in result


# --- DeepSeekClient tests ---

@pytest.mark.asyncio
async def test_client_basic_call():
    responses = [
        FakeResponse('{"choices": [{"message": {"content": "{\\"result\\": \\"ok\\"}"}}]}')
    ]
    fake_http = FakeAsyncClient(responses)
    client = DeepSeekClient(api_key="sk-test")

    result = await client.call("agent1", [{"role": "user", "content": "hello"}], _client=fake_http)
    assert result == '{"result": "ok"}'


@pytest.mark.asyncio
async def test_client_retry_on_5xx():
    responses = [
        FakeResponse("", status_code=500),
        FakeResponse("", status_code=503),
        FakeResponse('{"choices": [{"message": {"content": "{\\"ok\\": true}"}}]}'),
    ]
    fake_http = FakeAsyncClient(responses)
    client = DeepSeekClient(api_key="sk-test")

    result = await client.call("agent1", [{"role": "user", "content": "hello"}], _client=fake_http)
    assert result == '{"ok": true}'
    assert fake_http.call_count == 3


@pytest.mark.asyncio
async def test_client_json_fix_retry():
    responses = [
        FakeResponse('{"choices": [{"message": {"content": "{\\"broken\\": "}}]}'),
        FakeResponse('{"choices": [{"message": {"content": "{\\"fixed\\": true}"}}]}'),
    ]
    fake_http = FakeAsyncClient(responses)
    client = DeepSeekClient(api_key="sk-test")

    result = await client.call("agent2", [{"role": "user", "content": "analyze"}], _client=fake_http)
    assert '"fixed"' in result


@pytest.mark.asyncio
async def test_client_progress_callback():
    events = []
    async def on_progress(event):
        events.append(event)

    responses = [
        FakeResponse('{"choices": [{"message": {"content": "{\\"done\\": true}"}}]}')
    ]
    fake_http = FakeAsyncClient(responses)
    client = DeepSeekClient(api_key="sk-test", progress_callback=on_progress)

    await client.call("agent1", [{"role": "user", "content": "hello"}], _client=fake_http)
    assert len(events) == 2
    assert events[0]["status"] == "running"
    assert events[1]["status"] == "done"


@pytest.mark.asyncio
async def test_client_retry_on_network_error():
    """Verify that ConnectError on first attempt triggers retry and succeeds on second."""
    success = FakeResponse('{"choices": [{"message": {"content": "{\\"ok\\": true}"}}]}')
    call_count = 0

    class ErrorThenSuccessClient:
        def __init__(self, success_response):
            self._success = success_response
            self.call_count = 0

        async def post(self, url, json=None, headers=None, timeout=None):
            self.call_count += 1
            if self.call_count == 1:
                raise httpx.ConnectError("Connection refused")
            return self._success

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def aclose(self):
            pass

    fake_http = ErrorThenSuccessClient(success)
    client = DeepSeekClient(api_key="sk-test")

    result = await client.call("agent1", [{"role": "user", "content": "hello"}], _client=fake_http)
    assert result == '{"ok": true}'
    assert fake_http.call_count == 2
