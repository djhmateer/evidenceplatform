from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
import uvicorn
import os
import logging
from logging.handlers import RotatingFileHandler
from fastapi.middleware.cors import CORSMiddleware

# Create logs directory if it doesn't exist
os.makedirs("logs", exist_ok=True)

# Configure logging to file and console
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        RotatingFileHandler(
            "logs/1debug.log",
            maxBytes=10_000_000,  # 10MB
            backupCount=5
        ),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
from starlette.middleware.base import BaseHTTPMiddleware
from browsing_platform.server.routes import account, post, media, media_part, archiving_session, login, search, \
    permissions, tags, annotate
from browsing_platform.server.services.token_manager import check_token
from dotenv import load_dotenv

load_dotenv()
is_dev = os.getenv("BROWSING_PLATFORM_DEV", "")
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


class TokenAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # logger.info(f"Request: {request.method} {request.url.path}")
        if not is_dev:
            if request.url.path.startswith("/archives") or request.url.path.startswith("/thumbnails"):
                token = request.query_params.get("token")
                if not token or not check_token(token):
                    logger.warning(f"Unauthorized access attempt: {request.url.path}")
                    return Response("Unauthorized", status_code=401)
        response = await call_next(request)
        # logger.info(f"Response: {request.method} {request.url.path} -> {response.status_code}")
        return response


app.add_middleware(TokenAuthMiddleware)
for r in [
    account.router,
    post.router,
    media.router,
    media_part.router,
    annotate.router,
    archiving_session.router,
    search.router,
    login.router,
    permissions.router,
    tags.router
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
    if full_path and os.path.isfile(file_path):
        # logger.info(f"SPA catch-all: Serving static file -> {file_path}")
        return FileResponse(file_path)

    # logger.info(f"SPA catch-all: Serving index.html for -> {full_path or '/'}")
    return FileResponse(os.path.join(build_dir, "index.html"))

if __name__ == "__main__":
    uvicorn.run("browse:app", host="127.0.0.1", port=4444, reload=True)
