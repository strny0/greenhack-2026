"""The agent's prompt plumbing: instructions reach every turn, and the native
Anthropic path sends cache breakpoints. No network: a FunctionModel stands in for
the LLM, and the Anthropic client gets a mock HTTP transport."""
from __future__ import annotations

import json

import httpx
import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from anthropic import AsyncAnthropic

from app import agent as ag
from app.data_loader import store


def _deps(selection=None):
    return ag.Deps(timestamp=store.timestamps[0], selection=selection)


@pytest.mark.anyio
async def test_instructions_sent_on_follow_up_turns():
    seen: list[str | None] = []

    def model(messages, info: AgentInfo) -> ModelResponse:
        seen.append(messages[-1].instructions)
        return ModelResponse(parts=[TextPart("ok")])

    history = ag._to_history(
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    )
    with ag.agent.override(model=FunctionModel(model)):
        await ag.agent.run("and now?", deps=_deps(), message_history=history)
    assert seen and seen[0] and "Grid Pulse" in seen[0]


@pytest.mark.anyio
async def test_selection_context_sent_on_follow_up_turns():
    seen: list[str] = []

    def model(messages, info: AgentInfo) -> ModelResponse:
        seen.append(messages[-1].instructions or "")
        return ModelResponse(parts=[TextPart("ok")])

    line_id = ag.engine.base_frame(store.timestamps[0]).lines[0].id
    history = ag._to_history(
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    )
    with ag.agent.override(model=FunctionModel(model)):
        await ag.agent.run(
            "what about this line?",
            deps=_deps(ag.Selection(kind="line", id=line_id)),
            message_history=history,
        )
    assert "OPERATOR SELECTION" in seen[0] and line_id in seen[0]


@pytest.mark.anyio
async def test_anthropic_request_carries_cache_breakpoints(monkeypatch):
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant",
            "model": "claude-sonnet-5-5", "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 10, "output_tokens": 2},
        })

    monkeypatch.setattr(ag.config, "AI_USE_ANTHROPIC", True)
    monkeypatch.setattr(ag.config, "AI_ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    monkeypatch.setattr(ag.config, "AI_API_KEY", "test-key")
    monkeypatch.setattr(ag.config, "AI_MODEL", "claude-sonnet-5-5")
    model = ag._model()
    assert isinstance(model, AnthropicModel)
    client = AsyncAnthropic(
        api_key="test-key", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    model = AnthropicModel(
        "claude-sonnet-5-5", provider=AnthropicProvider(anthropic_client=client),
        settings=model.settings,
    )
    with ag.agent.override(model=model):
        await ag.agent.run("status?", deps=_deps())

    body = bodies[0]
    assert body["tools"][-1].get("cache_control")  # tool list cached
    assert isinstance(body["system"], list) and body["system"][0].get("cache_control")
    assert "Grid Pulse" in body["system"][0]["text"]
    assert body.get("cache_control")  # automatic breakpoint on the conversation


@pytest.fixture
def anyio_backend():
    return "asyncio"
