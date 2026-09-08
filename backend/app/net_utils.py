from fastapi import Request


def client_ip(request: Request) -> str:
    """Behind the ALB the real client IP arrives in X-Forwarded-For; fall
    back to the direct peer address for local dev."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"
