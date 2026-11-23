# Remotion render task for Cloud Run Jobs.
# One generic image per Remotion version: it holds Chrome Headless Shell, the compositor (ffmpeg) and
# @remotion/renderer, never your project. Each render uploads its own bundle to the bucket.
# Base and Chrome libraries follow https://www.remotion.dev/docs/docker.
FROM node:22-bookworm-slim

# Chrome Headless Shell libraries (Remotion docs) + CA store for https fonts/assets
# + CJK and emoji fonts, so text that relies on system fonts renders like it does on a desktop.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libnss3 libdbus-1-3 libatk1.0-0 libgbm-dev libasound2 libxrandr2 libxkbcommon-dev \
      libxfixes3 libxcomposite1 libxdamage1 libatk-bridge2.0-0 libpango-1.0-0 libcairo2 libcups2 \
      ca-certificates fonts-noto-core fonts-noto-cjk fonts-noto-color-emoji fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

ARG REMOTION_VERSION
WORKDIR /app
RUN test -n "$REMOTION_VERSION" \
    && npm init -y >/dev/null \
    && npm install --omit=dev --no-audit --no-fund "remotion@$REMOTION_VERSION" "@remotion/renderer@$REMOTION_VERSION" \
    && node -e "import('@remotion/renderer').then(m => m.ensureBrowser())"

COPY task.mjs /app/task.mjs
ENV REMOTION_VERSION=$REMOTION_VERSION
CMD ["node", "/app/task.mjs"]
