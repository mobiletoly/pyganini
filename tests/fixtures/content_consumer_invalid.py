from starlette.requests import Request

from pyganini import AdditionalPage, AdditionalPageSource, Page, content

AdditionalPage(1)
content.Config(root="content")
content.check("content")


def wrong(request: Request) -> Page:
    return Page()


source: AdditionalPageSource = wrong
