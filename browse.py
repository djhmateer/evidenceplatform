from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
import os
from fastapi.middleware.cors import CORSMiddleware
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
        if not is_dev:
            if request.url.path.startswith("/archives") or request.url.path.startswith("/thumbnails"):
                token = request.query_params.get("token")
                if not token or not check_token(token):
                    return Response("Unauthorized", status_code=401)
        return await call_next(request)


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
# @app.api_route("/{full_path:path}", methods=["GET"])
# async def serve_spa(request: Request, full_path: str):
#     # Let API routes return proper 404s
#     # if full_path.startswith("api/"):
#     #     return Response('{"detail":"Not Found"}', status_code=404, media_type="application/json")
#     # # Don't intercept archives or thumbnails
#     # if full_path.startswith("archives/") or full_path.startswith("thumbnails/"):
#     #     return Response(status_code=404)
#     build_dir = "browsing_platform/client/build"
#     file_path = os.path.join(build_dir, full_path)
#     if full_path and os.path.isfile(file_path):
#         return FileResponse(file_path)
#     return FileResponse(os.path.join(build_dir, "index.html"))

if __name__ == "__main__":
    uvicorn.run("browse:app", host="127.0.0.1", port=4444, reload=True)
