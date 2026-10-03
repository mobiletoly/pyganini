from pathlib import Path

from starlette.requests import Request
from starlette.responses import Response

from pyganini import AdditionalPage, AdditionalPageSource, PageMetadata, content

pages: content.Pages = content.new(content.Config(root=Path("content")))
source: AdditionalPageSource = pages.resolve
content.check(Path("content"))


def custom(request: Request) -> AdditionalPage | Response | None:
    return AdditionalPage("<p>Trusted</p>", metadata=PageMetadata("Title"))


async def asynchronous(request: Request) -> AdditionalPage | None:
    return pages.resolve(request)


source = custom
source = asynchronous
