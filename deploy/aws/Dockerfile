# Jakenew trading session image (ECS Fargate, launched daily by the MWAA DAG).
# Build from the repo root:   docker build -f deploy/aws/Dockerfile --build-arg CODE_VERSION=$(git rev-parse --short=12 HEAD) -t jakenew .
# No secrets or state are baked in: .env, keys, tokens and databases are excluded by .dockerignore and arrive at
# run time from Secrets Manager (env) and EFS (/data).
FROM python:3.13-slim

ARG CODE_VERSION=unknown
ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/Chicago \
    APP_DIR=/app \
    DATA_DIR=/data \
    CODE_VERSION=${CODE_VERSION}

# tzdata: log timestamps in Central time, matching the Windows run and HOW_IT_WORKS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 1000 --create-home jakenew

WORKDIR /app
COPY requirements.txt deploy/aws/requirements-aws.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-aws.txt

COPY . /app
COPY deploy/aws/entrypoint.py deploy/aws/export_state.py /app/

# Uid 1000 matches the EFS access point owner.
USER 1000
ENTRYPOINT ["python", "/app/entrypoint.py"]
