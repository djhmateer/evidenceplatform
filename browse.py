from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
import uvicorn
import os
import time
import logging
from logging.handlers import RotatingFileHandler
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()
is_production = os.getenv("ENVIRONMENT") == "production"

# Security check: prevent dev mode from being enabled in production
if is_production and os.getenv("BROWSING_PLATFORM_DEV") == "1":
    raise RuntimeError(
        "FATAL: BROWSING_PLATFORM_DEV=1 is set in production environment. "
        "This would bypass all authentication. Refusing to start."
    )

# Create logs directory if it doesn't exist
os.makedirs("logs", exist_ok=True)

# Configure logging to file (and console only in dev)
log_handler = RotatingFileHandler(
    "logs/1debug.log",
    maxBytes=10_000_000,  # 10MB
    backupCount=5
)
log_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

handlers = [log_handler]
if not is_production:
    handlers.append(logging.StreamHandler())

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=handlers
)

logger = logging.getLogger(__name__)
from starlette.middleware.base import BaseHTTPMiddleware
from browsing_platform.server.routes import account, post, media, media_part, archiving_session, login, search, \
    permissions, tags, annotate, share
from browsing_platform.server.services.sharing_manager import get_link_permissions
from browsing_platform.server.services.token_manager import check_token
app = FastAPI()

# CORS configuration
ALLOWED_ORIGINS = [
    "http://localhost:3000",      # Local React dev server
    "http://localhost:4444",      # Local API
]
if is_production:
    ALLOWED_ORIGINS = [
        "https://evidenceplatform.org",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the 'archives' directory statically
# middleware wraps all requests regardless of order
app.mount(
    "/archives",
    StaticFiles(directory="archives"),
    name="archives",
)
app.mount(
    "/thumbnails",
    StaticFiles(directory="thumbnails"),
    name="thumbnails"
)


class StaticFilesAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        if request.url.path.startswith("/archives") or request.url.path.startswith("/thumbnails"):
            # Prefer per-file token 'ft' which is bound to the file path and cannot be reused for other files.
            file_token = request.query_params.get("ft")
            try:
                # Use the request path (including leading slash) as the file_path binding.
                payload = decrypt_file_token(file_token, request.url.path)
            except FileTokenError as e:
                logger.warning(f"File token validation failed for {request.url.path}: {e}")
                return Response("Unauthorized", status_code=401)
            # access is allowed if the user supplied a valid login token or a share token
            # share tokens can be used to access static media even if the entities the media is attached to is beyond the share scope
            # this is fine because a user can not generate an encrypted payload containing their share token for arbitrary files without knowing the server secret
            if not check_token(payload.login_token).valid and not get_link_permissions(payload.login_token).view:
                logger.warning(f"Invalid embedded login token for {request.url.path}")
                return Response("Unauthorized", status_code=401)
        response = await call_next(request)

        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        if is_production:
            duration_ms = (time.time() - start_time) * 1000
            client_ip = request.headers.get("X-Real-IP", request.client.host if request.client else "unknown")
            logger.info(f"{client_ip} - {request.method} {request.url.path} - {response.status_code} - {duration_ms:.1f}ms")

        return response


app.add_middleware(StaticFilesAuthMiddleware)
for r in [
    account.router,
    post.router,
    media.router,
    media_part.router,
    annotate.router,
    tags.router,
    archiving_session.router,
    search.router,
    login.router,
    permissions.router,
    share.router,
]:
    app.include_router(r, prefix="/api")

# # # SPA catch-all route (must be last)
@app.api_route("/{full_path:path}", methods=["GET"])
async def serve_spa(request: Request, full_path: str):
    # Don't intercept broken API routes - let them 404 properly
    if full_path.startswith("api/"):
        logger.info(f"SPA catch-all: API route not found -> {full_path}")
        return Response('{"detail":"Not Found"}', status_code=404, media_type="application/json")

    build_dir = "browsing_platform/client/build"
    file_path = os.path.join(build_dir, full_path)

    # Serve actual static files if they exist
    if full_path and os.path.isfile(file_path):
        return FileResponse(file_path)

    # If it looks like a file request (has extension) but doesn't exist, return 404
    # This prevents returning index.html with 200 for missing .json, .js, .css, etc.
    if full_path and '.' in full_path.split('/')[-1]:
        logger.debug(f"SPA catch-all: File not found -> {full_path}")
        return Response('Not Found', status_code=404)

    # Otherwise, serve index.html for SPA client-side routing (e.g., /account/123)
    return FileResponse(os.path.join(build_dir, "index.html"))

if __name__ == "__main__":
    reload = not is_production
    uvicorn.run("browse:app", host="127.0.0.1", port=4444, reload=reload)
