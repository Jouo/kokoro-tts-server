"""Bound HTTP requests and restrict browser origins for the local API."""

from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from kokoro_server.settings import get_settings, normalize_origin


def server_origin(scheme, host, port):
    if ":" in host:
        host = f"[{host}]"
    return normalize_origin(f"{scheme}://{host}:{port}")


class RequestSafety:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        settings = get_settings()
        headers = scope.get("headers", [])
        hosts = [v.decode("latin-1") for k, v in headers if k.lower() == b"host"]
        origins = [v.decode("latin-1") for k, v in headers if k.lower() == b"origin"]
        allowed_hosts = {"localhost", "127.0.0.1", "::1"}
        try:
            if len(hosts) != 1:
                raise ValueError("Invalid Host")
            request_origin = normalize_origin(f'{scope["scheme"]}://{hosts[0]}')
            allowed_server_origins = {
                server_origin(scope["scheme"], host, settings.port)
                for host in allowed_hosts
            }
            if request_origin not in allowed_server_origins or len(origins) > 1:
                raise ValueError("Invalid Host or Origin")
            if origins and normalize_origin(origins[0]) not in [request_origin, *settings.additional_origins]:
                raise ValueError("Untrusted Origin")
        except ValueError:
            return await JSONResponse({"detail": "Untrusted Host or Origin"}, status_code=403)(scope, receive, send)

        cors = CORSMiddleware(self.handle_body, allow_origins=settings.additional_origins,
                              allow_methods=["GET", "POST"], allow_headers=["*"])
        await cors(scope, receive, send)

    async def handle_body(self, scope, receive, send):
        settings = get_settings()
        headers = scope.get("headers", [])
        limit = 6 * settings.input_limit_bytes + 65536
        lengths = [v for k, v in headers if k.lower() == b"content-length"]
        if lengths:
            if len(lengths) != 1 or not lengths[0].isdigit():
                return await JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)(scope, receive, send)
            length = lengths[0].lstrip(b"0") or b"0"
            max_length = str(limit).encode("ascii")
            if len(length) > len(max_length) or (len(length) == len(max_length) and length > max_length):
                return await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
                return await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        async def replay():
            nonlocal body
            if body is not None:
                data = bytes(body)
                body = None
                return {"type": "http.request", "body": data, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
