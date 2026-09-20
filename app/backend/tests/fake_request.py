"""A real `Request` for tests that call a router function directly.

Most of this suite calls endpoint functions straight rather than through an HTTP
client. That is fast and clear, but it means the test has to supply everything
FastAPI would have supplied, and it fails loudly the day an endpoint asks for
something new:

    TypeError: checkout() missing 1 required positional argument: 'request'

That is the third form of the same trap in this suite. A parameter defaulted to
`Depends(...)` or `Query(...)` is worse, because a direct call silently receives
the SENTINEL OBJECT instead of a session or a value, and the failure surfaces
somewhere else entirely (`'Depends' object has no attribute 'execute'`, or
`'<=' not supported between instances of 'int' and 'Query'`). A required
parameter at least names itself. Either way the rule is the same: when you call
an endpoint directly, pass every argument it declares.

Defaults here are an anonymous request - no cookies, so no impersonation claim
and no session token, and no headers, so `cf-connecting-ip` falls through to
`client.host` and the user agent is empty. Pass cookies/headers for the paths
that read them.
"""

from __future__ import annotations

from fastapi import Request

__all__ = ["anon_request"]


def anon_request(
    *,
    method: str = "GET",
    path: str = "/",
    cookies: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    client: tuple[str, int] = ("127.0.0.1", 50000),
) -> Request:
    """Build a Starlette Request from a minimal ASGI scope."""
    raw: list[tuple[bytes, bytes]] = [
        (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
    ]
    if cookies:
        jar = "; ".join(f"{k}={v}" for k, v in cookies.items())
        raw.append((b"cookie", jar.encode()))
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": raw,
            "client": client,
            "server": ("testserver", 80),
        }
    )
