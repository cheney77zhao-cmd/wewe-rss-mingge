FROM node:22-bookworm-slim AS base
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends openssl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm@8.15.9
FROM base AS build
COPY . /usr/src/app
WORKDIR /usr/src/app
RUN --mount=type=cache,id=pnpm,target=/pnpm/store pnpm install --frozen-lockfile
RUN pnpm run -r build
RUN pnpm deploy --filter=server --prod /app
RUN pnpm deploy --filter=server --prod /app-sqlite
RUN cd /app && pnpm exec prisma generate
RUN cd /app-sqlite && rm -rf ./prisma && mv prisma-sqlite prisma && pnpm exec prisma generate
FROM base AS app-sqlite
COPY --from=build /app-sqlite /app
WORKDIR /app
EXPOSE 4000
ENV NODE_ENV=production HOST="0.0.0.0" SERVER_ORIGIN_URL="" MAX_REQUEST_PER_MINUTE=60 AUTH_CODE="" DATABASE_URL="file:../data/wewe-rss.db" DATABASE_TYPE="sqlite"
RUN chmod +x ./docker-bootstrap.sh
CMD ["./docker-bootstrap.sh"]
FROM base AS app
COPY --from=build /app /app
WORKDIR /app
EXPOSE 4000
ENV NODE_ENV=production HOST="0.0.0.0" SERVER_ORIGIN_URL="" MAX_REQUEST_PER_MINUTE=60 AUTH_CODE="" DATABASE_URL=""
RUN chmod +x ./docker-bootstrap.sh
CMD ["./docker-bootstrap.sh"]
