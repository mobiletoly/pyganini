import asyncio
import contextvars
import functools
import inspect
import threading
from collections.abc import Awaitable, Callable
from typing import Any, cast

import anyio
import pytest
from anyio.to_thread import current_default_thread_limiter, run_sync

from foundation_probes.callable_invocation import (
    CallableRejection,
    classify_callable,
    invoke_callable,
)


def sync_function(value: int) -> int:
    return value + 1


async def async_function(value: int) -> int:
    return value + 2


class Owner:
    def sync_method(self, value: int) -> int:
        return value + 3

    async def async_method(self, value: int) -> int:
        return value + 4


class SyncCallable:
    def __call__(self, value: int) -> int:
        return value + 5


class AsyncCallable:
    async def __call__(self, value: int) -> int:
        return value + 6


class WrappedPropertyCallable:
    inspected = False

    @property
    def __wrapped__(self) -> Callable[..., object]:
        self.inspected = True
        raise RuntimeError("classification executed application property")

    def __call__(self, value: int) -> int:
        return value + 8


class WrappedCallDescriptor:
    inspected = False

    @property
    def __wrapped__(self) -> Callable[..., object]:
        self.inspected = True
        raise RuntimeError("classification executed __call__ wrapper property")

    def __get__(
        self,
        instance: object,
        owner: type[object],
    ) -> Callable[[int], int]:
        return lambda value: value + 9


class DescriptorBackedCallable:
    __call__ = WrappedCallDescriptor()


def preserving_decorator(
    function: Callable[[int], Awaitable[int]],
) -> Callable[[int], Awaitable[int]]:
    @functools.wraps(function)
    async def wrapped(value: int) -> int:
        return await function(value)

    return wrapped


decorated_async = preserving_decorator(async_function)


def sync_returning_awaitable(value: int) -> Awaitable[int]:
    async def result() -> int:
        return value + 7

    return result()


async def async_generator() -> Any:
    yield 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("callable_value", "kind", "expected"),
    [
        (sync_function, "sync", 2),
        (async_function, "async", 3),
        (Owner().sync_method, "sync", 4),
        (Owner().async_method, "async", 5),
        (functools.partial(sync_function), "sync", 2),
        (functools.partial(async_function), "async", 3),
        (decorated_async, "async", 3),
        (SyncCallable(), "sync", 6),
        (AsyncCallable(), "async", 7),
        (sync_returning_awaitable, "sync", 8),
    ],
)
async def test_callable_matrix(
    callable_value: Callable[[int], int | Awaitable[int]],
    kind: str,
    expected: int,
) -> None:
    assert classify_callable(callable_value) == kind
    assert await invoke_callable(callable_value, 1) == expected


def test_async_generator_is_rejected_before_invocation() -> None:
    with pytest.raises(CallableRejection, match="callable phase: async-generator"):
        classify_callable(async_generator)


def test_callable_instance_wrapper_property_is_not_executed() -> None:
    callable_value = WrappedPropertyCallable()
    assert classify_callable(callable_value) == "sync"
    assert callable_value.inspected is False


def test_callable_instance_call_descriptor_is_rejected_without_inspection() -> None:
    callable_value = cast("Callable[[int], int]", DescriptorBackedCallable())
    descriptor = cast(
        "WrappedCallDescriptor",
        inspect.getattr_static(DescriptorBackedCallable, "__call__"),
    )
    with pytest.raises(CallableRejection, match="__call__ descriptor is unsupported"):
        classify_callable(callable_value)
    assert descriptor.inspected is False


@pytest.mark.anyio
async def test_sync_wrapper_around_async_function_is_offloaded() -> None:
    loop_thread = threading.get_ident()
    wrapper_thread: int | None = None

    @functools.wraps(async_function)
    def wrapped(value: int) -> Awaitable[int]:
        nonlocal wrapper_thread
        wrapper_thread = threading.get_ident()
        return async_function(value)

    callable_value = cast("Callable[[int], int | Awaitable[int]]", wrapped)
    assert classify_callable(callable_value) == "sync"
    assert await invoke_callable(callable_value, 1) == 3
    assert wrapper_thread is not None
    assert wrapper_thread != loop_thread


@pytest.mark.anyio
async def test_sync_work_is_offloaded_and_context_propagates() -> None:
    loop_thread = threading.get_ident()
    context = contextvars.ContextVar("probe", default="missing")
    context.set("present")

    def observe() -> tuple[int, str]:
        return threading.get_ident(), context.get()

    worker_thread, value = await invoke_callable(observe)
    assert worker_thread != loop_thread
    assert value == "present"


@pytest.mark.anyio
async def test_sync_exception_type_and_traceback_are_preserved() -> None:
    class MarkerError(RuntimeError):
        pass

    def fail_from_worker() -> None:
        raise MarkerError("worker failed")

    with pytest.raises(MarkerError, match="worker failed") as captured:
        await invoke_callable(fail_from_worker)
    assert captured.value.__traceback__ is not None
    frames = [
        frame.function for frame in inspect.getinnerframes(captured.value.__traceback__)
    ]
    assert "fail_from_worker" in frames


@pytest.mark.anyio
async def test_sync_work_does_not_block_event_loop() -> None:
    release = threading.Event()
    entered = threading.Event()
    ticked = False

    def blocking() -> str:
        entered.set()
        release.wait(timeout=2)
        return "done"

    async def tick() -> None:
        nonlocal ticked
        while not entered.is_set():
            await anyio.sleep(0)
        ticked = True
        release.set()

    result: str | None = None
    async with anyio.create_task_group() as group:
        group.start_soon(tick)
        result = await invoke_callable(blocking)
    assert ticked
    assert result == "done"


@pytest.mark.anyio
async def test_cancellation_before_invocation_does_not_start_sync_work() -> None:
    called = False

    def work() -> None:
        nonlocal called
        called = True

    with anyio.CancelScope() as scope:
        scope.cancel()
        await invoke_callable(work)
    assert not called


@pytest.mark.anyio
async def test_cancellation_during_sync_work_cancels_waiter_not_thread() -> None:
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def work() -> None:
        entered.set()
        release.wait(timeout=2)
        finished.set()

    async def cancel_when_entered(scope: anyio.CancelScope) -> None:
        while not entered.is_set():
            await anyio.sleep(0)
        scope.cancel()

    with anyio.CancelScope() as scope:
        async with anyio.create_task_group() as group:
            group.start_soon(cancel_when_entered, scope)
            await invoke_callable(work)
    assert not finished.is_set()
    release.set()
    await run_sync(finished.wait, 2)
    assert finished.is_set()


@pytest.mark.anyio
async def test_default_thread_limiter_is_not_mutated() -> None:
    limiter = current_default_thread_limiter()
    before = limiter.total_tokens
    await invoke_callable(sync_function, 1)
    assert limiter.total_tokens == before


def test_probe_never_creates_a_second_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("asyncio.run must not be used")

    monkeypatch.setattr(asyncio, "run", forbidden)
    assert "asyncio.run" not in inspect.getsource(invoke_callable)
