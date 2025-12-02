from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
import uvicorn
import os
import logging
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
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
        logger.info(f"Request: {request.method} {request.url.path}")
        if not is_dev:
            if request.url.path.startswith("/archives") or request.url.path.startswith("/thumbnails"):
                token = request.query_params.get("token")
                if not token or not check_token(token):
                    logger.warning(f"Unauthorized access attempt: {request.url.path}")
                    return Response("Unauthorized", status_code=401)
        response = await call_next(request)
        logger.info(f"Response: {request.method} {request.url.path} -> {response.status_code}")
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

# Serve React build static assets - this is the css and js files
# app.mount("/static", StaticFiles(directory="browsing_platform/client/build/static"), name="static")

# # # SPA catch-all route (must be last)
@app.api_route("/{full_path:path}", methods=["GET"])
async def serve_spa(request: Request, full_path: str):
    # Redirect API routes with trailing slash to non-trailing version - dm hope I've fixed this
    # if full_path.startswith("api/") and full_path.endswith("/"):
    #     new_path = "/" + full_path.rstrip("/")
    #     if request.url.query:
    #         new_path += f"?{request.url.query}"
    #     return RedirectResponse(url=new_path, status_code=307)

    # Don't intercept broken API routes - let them 404 properly
    if full_path.startswith("api/"):
        logger.info(f"SPA catch-all: API route not found -> {full_path}")
        return Response('{"detail":"Not Found"}', status_code=404, media_type="application/json")
    # Don't intercept archives or thumbnails
    # if full_path.startswith("archives/") or full_path.startswith("thumbnails/"):
    #     logger.info(f"SPA catch-all: Static file not found -> {full_path}")
    #     return Response(status_code=404)

    build_dir = "browsing_platform/client/build"
    file_path = os.path.join(build_dir, full_path)      
    if full_path and os.path.isfile(file_path):
        logger.info(f"SPA catch-all: Serving static file -> {file_path}")
        return FileResponse(file_path)
    logger.info(f"SPA catch-all: Serving index.html for -> {full_path or '/'}")
    return FileResponse(os.path.join(build_dir, "index.html"))

if __name__ == "__main__":
    uvicorn.run("browse:app", host="127.0.0.1", port=4444, reload=True)
