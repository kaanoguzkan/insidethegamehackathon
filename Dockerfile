# The Brain: REST API + Match Data MCP server + agent workflow.
# Build:  docker build -t matchmind-brain .      Run:  docker run -p 8000:8000 matchmind-brain
# Astral's image (Debian bookworm-slim, Python 3.12 and uv) from GitHub's registry rather than Docker Hub: Docker Hub's
# token service rate-limits and times out, which broke CI and deploys. Both stages share it, so the venv's Python matches.
FROM ghcr.io/astral-sh/uv:0.8-python3.12-bookworm-slim AS build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
# Dependencies first, so code changes do not invalidate the layer.
COPY pyproject.toml uv.lock README.md LICENSE.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --extra brain --extra openai --extra foundry --extra telemetry --no-editable

FROM ghcr.io/astral-sh/uv:0.8-python3.12-bookworm-slim
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY apps ./apps
COPY data ./data
ENV PATH="/app/.venv/bin:$PATH" MATCHMIND_DATA=/app/data MATCHMIND_LLM=offline PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"
CMD ["uvicorn", "apps.brain.main:app", "--host", "0.0.0.0", "--port", "8000"]
