import os

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.database import Base, engine
from app import models  # noqa: F401 -- register models with Base metadata
from app.routes_auth import router as auth_router
from app.routes_session import router as session_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Zero Trust Continuous Authentication API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev only; tighten to the real frontend origin for prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(session_router)


@app.get("/health")
def health():
    return {"status": "ok"}


# Serve the built React app (if present) so a single container can host both
# the API and the SPA in the "VM + managed DB" deployment.
_frontend_dist = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(_frontend_dist):
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")

    # React Router serves paths like /login, /register, /dashboard client-side.
    # A direct navigation or refresh hits this server for that exact path, which
    # StaticFiles 404s on (it only auto-serves index.html for "/"). Fall back to
    # index.html for any GET that isn't a real API route so those URLs work too.
    _api_prefixes = ("/auth", "/session", "/health", "/docs", "/openapi.json", "/redoc")

    @app.exception_handler(StarletteHTTPException)
    async def spa_fallback(request: Request, exc: StarletteHTTPException):
        if (
            exc.status_code == 404
            and request.method == "GET"
            and not request.url.path.startswith(_api_prefixes)
        ):
            return FileResponse(os.path.join(_frontend_dist, "index.html"))
        # Must RETURN a response, not re-raise: re-raising escapes the handler
        # as an unhandled exception and every 400/401/403 in the app comes back
        # to the client as a 500 instead. That also broke the frontend's
        # `err.status === 403` check for a risk-engine-terminated session.
        return await http_exception_handler(request, exc)
