# Stage 1: Build the UI
FROM node:20-alpine AS ui-builder
WORKDIR /web
# Install pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
COPY web/apps/ui/package.json ./apps/ui/
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

# Stage 2: Python environment
FROM ghcr.io/astral-sh/uv:python3.12-alpine
WORKDIR /app

# Install git as it's needed for cloning repos
RUN apk add --no-cache git

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY app/ ./app/
COPY scripts/ ./scripts/
# Copy the built UI to a directory the Python app can serve
COPY --from=ui-builder /web/apps/ui/dist ./static

ENV DEPLOY_BASE_DIR=/data/deploy/repos
ENV CONFIGURED_PROJECTS_FILE=/data/configured_projects.json

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
