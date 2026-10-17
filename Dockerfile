# AWS Lambda container image (arm64 / Graviton: ~20% cheaper per GB-second).
FROM ghcr.io/astral-sh/uv:0.5.11 AS uv

FROM public.ecr.aws/lambda/python:3.13 AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /build
COPY pyproject.toml uv.lock ./
# Runtime dependencies only, exactly as locked.
RUN uv export --frozen --no-dev --no-emit-project --no-hashes -o requirements.txt \
 && uv pip install --python /var/lang/bin/python --target /asset -r requirements.txt
COPY src/market_ingest /asset/market_ingest

FROM public.ecr.aws/lambda/python:3.13
COPY --from=build /asset ${LAMBDA_TASK_ROOT}
CMD ["market_ingest.handler.lambda_handler"]
