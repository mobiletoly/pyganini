from starlette.middleware import Middleware

from app.security import ExampleRoutePolicyMiddleware

MIDDLEWARE: tuple[Middleware, ...] = (
    Middleware(ExampleRoutePolicyMiddleware, "users"),
)
