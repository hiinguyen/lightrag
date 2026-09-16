"""Lead-handoff proposal through the portal chat stream.

The chat stream only ever *proposes* a lead — see
app.services.business_lead_sentinel — and never writes one. These tests hold
that promise: the sentinel never reaches the customer, a card only ever
describes a package that is really in the active catalogue, and a malformed
sentinel degrades to a clean answer with no lead_prompt event.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services import business_chat
from app.services.business_rag import (
    BUSINESS_AUDIENCE,
    BusinessRetrievalResult,
    BusinessSource,
)
from app.services.llm.types import StreamChunk

STREAM_URL = "/api/v1/business/chat/stream"

_CONTEXT = "[1] Bang gia san pham | tr.3\nAnfo dùng cho mỏ đá lộ thiên."


@pytest.fixture
def stub_retrieval(monkeypatch):
    async def _fake_search(db, question, top_k=5):
        return BusinessRetrievalResult(
            context=_CONTEXT,
            sources=(BusinessSource(label="Bang gia san pham", page_no=3),),
            allowed_document_ids=(11,),
        )

    monkeypatch.setattr(business_chat, "business_search", _fake_search)


@pytest.fixture
async def business_workspace(make_workspace):
    return await make_workspace(
        name="Cong khai doanh nghiep", audience=BUSINESS_AUDIENCE
    )


@pytest.fixture
async def catalog(make_package):
    return [
        await make_package(name="Cung ứng thuốc nổ", category="Vật liệu nổ", sort_order=10),
        await make_package(name="Dịch vụ nổ mìn trọn gói", category="Dịch vụ", sort_order=20),
    ]


def parse_sse(body: str) -> list[tuple[str, dict]]:
    import json

    events: list[tuple[str, dict]] = []
    for frame in body.split("\n\n"):
        name = payload = None
        for line in frame.splitlines():
            if line.startswith("event:"):
                name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                payload = json.loads(line[len("data:"):].strip())
        if name is not None and payload is not None:
            events.append((name, payload))
    return events


def names(events) -> list[str]:
    return [name for name, _ in events]


def payload_of(events, name: str) -> dict:
    for event_name, payload in events:
        if event_name == name:
            return payload
    raise AssertionError(f"no {name!r} event in {names(events)}")


def streamed_text(events) -> str:
    return "".join(p["text"] for n, p in events if n == "delta")


async def ask(client: AsyncClient, message: str = "Tôi muốn ký hợp đồng cung cấp anfo"):
    response = await client.post(STREAM_URL, json={"message": message})
    assert response.status_code == 200, response.text
    return parse_sse(response.text), response.text


async def test_lead_intent_returns_prose_and_a_lead_prompt(
    business_client: AsyncClient, business_workspace, catalog, stub_retrieval, mock_llm_provider
):
    mock_llm_provider.chunks = [
        StreamChunk(type="text", text="Vâng, tôi ghi nhận nhu cầu của bạn. "),
        StreamChunk(
            type="text",
            text=f"[[LEAD: {catalog[0].id}|Cần 200 tấn anfo cho mỏ đá, ngân sách khoảng 200 triệu]]",
        ),
    ]

    events, raw = await ask(business_client)

    assert "LEAD" not in raw
    assert streamed_text(events).strip() == "Vâng, tôi ghi nhận nhu cầu của bạn."
    prompt = payload_of(events, "lead_prompt")
    assert prompt["summary"] == "Cần 200 tấn anfo cho mỏ đá, ngân sách khoảng 200 triệu"
    assert [p["name"] for p in prompt["packages"]] == ["Cung ứng thuốc nổ"]


async def test_lead_prompt_arrives_before_complete(
    business_client: AsyncClient, business_workspace, catalog, stub_retrieval, mock_llm_provider
):
    mock_llm_provider.chunks = [
        StreamChunk(type="text", text=f"Đã rõ.[[LEAD: |Cần tư vấn hợp đồng tổng thể]]"),
    ]

    events, _ = await ask(business_client)

    order = names(events)
    assert order.index("lead_prompt") < order.index("complete")
    assert order[-1] == "complete"


async def test_lead_prompt_with_no_package_still_carries_a_summary(
    business_client: AsyncClient, business_workspace, catalog, stub_retrieval, mock_llm_provider
):
    mock_llm_provider.chunks = [
        StreamChunk(type="text", text="Đã rõ.[[LEAD: |Cần tư vấn hợp đồng tổng thể]]"),
    ]

    events, _ = await ask(business_client)

    prompt = payload_of(events, "lead_prompt")
    assert prompt["summary"] == "Cần tư vấn hợp đồng tổng thể"
    assert prompt["packages"] == []


async def test_hallucinated_package_id_is_dropped_from_the_lead_prompt(
    business_client: AsyncClient, business_workspace, catalog, stub_retrieval, mock_llm_provider
):
    mock_llm_provider.chunks = [
        StreamChunk(type="text", text="Đã rõ.[[LEAD: 9999|Cần tư vấn]]"),
    ]

    events, raw = await ask(business_client)

    prompt = payload_of(events, "lead_prompt")
    assert prompt["packages"] == []


async def test_truncated_lead_sentinel_leaves_a_clean_answer_and_no_prompt(
    business_client: AsyncClient, business_workspace, catalog, stub_retrieval, mock_llm_provider
):
    mock_llm_provider.chunks = [StreamChunk(type="text", text="Đã rõ.[[LEAD: 1|Cần báo giá")]

    events, raw = await ask(business_client)

    assert "LEAD" not in raw
    assert streamed_text(events) == "Đã rõ."
    assert "lead_prompt" not in names(events)


async def test_no_sentinel_means_no_lead_prompt_event(
    business_client: AsyncClient, business_workspace, catalog, stub_retrieval, mock_llm_provider
):
    mock_llm_provider.chunks = [StreamChunk(type="text", text="Anfo dùng cho mỏ đá lộ thiên.")]

    events, _ = await ask(business_client)

    assert "lead_prompt" not in names(events)


async def test_lead_prompt_is_not_carried_in_the_complete_payload(
    business_client: AsyncClient, business_workspace, catalog, stub_retrieval, mock_llm_provider
):
    """The draft is ephemeral — the stand-alone event is the only channel."""
    mock_llm_provider.chunks = [
        StreamChunk(type="text", text="Đã rõ.[[LEAD: |Cần tư vấn hợp đồng tổng thể]]")
    ]

    events, _ = await ask(business_client)

    assert "lead_prompt" not in payload_of(events, "complete")


async def test_lead_prompt_is_not_persisted_to_history(
    business_client: AsyncClient, business_workspace, catalog, stub_retrieval, mock_llm_provider
):
    mock_llm_provider.chunks = [
        StreamChunk(type="text", text="Đã rõ.[[LEAD: |Cần tư vấn hợp đồng tổng thể]]")
    ]
    await ask(business_client)

    history = await business_client.get("/api/v1/business/chat/history")
    messages = history.json()["data"]["messages"]

    assert "leadPrompt" not in messages[-1]
    assert "lead_prompt" not in history.text
