from __future__ import annotations

from pyganini import csrf

SECRET = b"0123456789abcdef0123456789abcdef"
bad_secret_guard = csrf.Guard(secret="not bytes")
bad_age_guard = csrf.Guard(secret=SECRET, max_age="12")
bad_same_site_guard = csrf.Guard(secret=SECRET, same_site=1)
bad_request: object = object()
bad_form_token: object = object()
bad_secret_guard.validate(bad_request, bad_form_token)
