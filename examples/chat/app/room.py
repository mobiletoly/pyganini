"""Application-owned in-memory chat room."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class Message:
    identifier: int
    author: str
    body: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Subscription:
    identifier: int
    replay: tuple[Message, ...]
    queue: asyncio.Queue[Message]


class ChatRoom:
    """Keep messages and live subscribers inside one application process."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._next_message_id = 0
        self._next_subscription_id = 0
        self._messages: list[Message] = []
        self._subscribers: dict[int, asyncio.Queue[Message]] = {}

    async def messages(self) -> tuple[Message, ...]:
        async with self._lock:
            return tuple(self._messages)

    async def publish(self, author: str, body: str) -> Message:
        async with self._lock:
            self._next_message_id += 1
            message = Message(
                identifier=self._next_message_id,
                author=author,
                body=body,
                created_at=datetime.now(UTC),
            )
            self._messages.append(message)
            for queue in self._subscribers.values():
                queue.put_nowait(message)
            return message

    async def subscribe(self, after_id: int) -> Subscription:
        async with self._lock:
            self._next_subscription_id += 1
            identifier = self._next_subscription_id
            queue: asyncio.Queue[Message] = asyncio.Queue()
            self._subscribers[identifier] = queue
            replay = tuple(
                message for message in self._messages if message.identifier > after_id
            )
            return Subscription(identifier, replay, queue)

    async def unsubscribe(self, subscription_id: int) -> None:
        async with self._lock:
            self._subscribers.pop(subscription_id, None)
