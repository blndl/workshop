# One image for every alarm service; each container runs a different command.
# Build from the repo root:  docker build -f infra/docker/Dockerfile -t alarm .
# For a Raspberry Pi or other arm64 box: docker buildx build --platform linux/arm64 ...

# --- dashboard ---------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# --- services ----------------------------------------------------------------
FROM python:3.12-slim
# HOME=/tmp: compose may run the container as a host UID that has no home here.
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 HOME=/tmp

# Run as an unprivileged user. compose.yml overrides the UID with the host
# user's (HOST_UID), so bind-mounted .secrets/ and data/ stay accessible.
ARG UID=1000
RUN useradd --create-home --uid ${UID} alarm

WORKDIR /app
COPY protocol/python protocol/python
COPY simulator simulator
COPY services services
# Editable installs keep the repo layout (/app/.secrets, /app/data) that the CLIs expect.
RUN pip install \
      -e 'protocol/python[mqtt]' \
      -e simulator \
      -e services/alarm-core \
      -e 'services/camera[webcam]' \
      -e services/notifier \
      -e services/api \
 && mkdir -p /app/data && chown alarm /app/data
COPY --from=web /web/dist web/dist

USER alarm
CMD ["python", "-m", "alarm_core", "--help"]
