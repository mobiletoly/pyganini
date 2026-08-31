"""Application-owned room behavior."""

from __future__ import annotations

import pytest

from app.room import ChatRoom


@pytest.mark.anyio
async def test_room_assigns_ids_and_returns_immutable_snapshots() -> None:
    room = ChatRoom()

    first = await room.publish("Ada", "Hello")
    second = await room.publish("Grace", "Hi")

    assert first.identifier == 1
    assert second.identifier == 2
    assert await room.messages() == (first, second)


@pytest.mark.anyio
async def test_subscription_orders_replay_before_live_delivery() -> None:
    room = ChatRoom()
    first = await room.publish("Ada", "First")

    subscription = await room.subscribe(after_id=0)
    second = await room.publish("Grace", "Second")

    assert subscription.replay == (first,)
    assert await subscription.queue.get() == second


@pytest.mark.anyio
async def test_subscription_cursor_and_idempotent_unsubscribe() -> None:
    room = ChatRoom()
    first = await room.publish("Ada", "First")
    second = await room.publish("Grace", "Second")

    subscription = await room.subscribe(after_id=first.identifier)
    assert subscription.replay == (second,)

    await room.unsubscribe(subscription.identifier)
    await room.unsubscribe(subscription.identifier)
    await room.publish("Katherine", "Third")
    assert subscription.queue.empty()
