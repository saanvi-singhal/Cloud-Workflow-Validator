# The `test` stage is never used by the final stage, so a default build skips it.
# Expect UNREACHABLE_NODE for `test`.
FROM python:3.12-slim AS base
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS test
COPY . .
RUN pytest

FROM base AS app
COPY . .
USER nobody
CMD ["python", "app.py"]
