FROM node:24-alpine AS base

WORKDIR /app

FROM base AS dependencies

COPY frontend/package.json frontend/package-lock.json ./

RUN npm ci

FROM dependencies AS check

COPY frontend/ ./
COPY .gitignore ./.gitignore

RUN npm ci
RUN npm run check && npm run lint

FROM dependencies AS build

ARG SITE_ORIGIN=http://localhost:3000
ENV ORIGIN=$SITE_ORIGIN

COPY frontend/ ./

RUN npm ci
RUN npm run build

FROM base AS production-dependencies

COPY frontend/package.json frontend/package-lock.json ./

RUN npm ci --omit=dev

FROM base AS runtime

ENV HOST=0.0.0.0 PORT=3000

RUN addgroup -S appgroup && adduser -S appuser -G appgroup

WORKDIR /app

COPY --from=build --chown=appuser:appgroup /app/build ./build
COPY --from=build --chown=appuser:appgroup /app/package.json ./package.json
COPY --from=production-dependencies --chown=appuser:appgroup /app/node_modules ./node_modules

USER appuser

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD ["node", "-e", "fetch('http://127.0.0.1:3000/health').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"]

CMD ["node", "build"]
