from __future__ import annotations

from pyganini import sse

bad_data = sse.Event(data=1)
bad_id = sse.Event(id=object())
bad_name = sse.Event(name=object())
bad_retry = sse.Event(retry="2000")
bad_positional = sse.Event("payload")
bad_event = sse.encode_event(object())
bad_comment = sse.encode_comment(object())
bad_request = sse.last_event_id(object())
