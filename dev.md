# notes on how to start the app normally in dev 

```bash
# CLIENT FRONTEND
# react - vite - port 5173 - custom node webserver

# webpack - port 3000
cd browsing_platform/client 

# pnpm install
pnpm update

# this is for the newer compiler (vite - faster)
# pnpm dev

# this is for create react app which uses webpack
# or we can use pnpm build then serve the html, css, and js from uvicorn
pnpm start

# SERVER BACKEND
uv lock --upgrade
uv sync

# dev flag bypasses token middleware in static file hosting (useful for dev)
# port 4444
BROWSING_PLATFORM_DEV=1 uv run python browse.py

# port 8000 by default (vanilla on eplatform)
# ENVIRONMENT=development uv run uvicorn main:app --reload


## Other front end commands
# pnpm build

# # port 4173 - prod port
# pnpm preview

# pnpm lint
```