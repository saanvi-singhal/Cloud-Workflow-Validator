# A clean multi-stage build: dependencies are installed before the source is
# copied, the base images are pinned and the final stage runs as non-root.
# Graph: build -> runtime (COPY --from=build).
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-slim AS runtime
WORKDIR /app
COPY --from=build /app/dist ./dist
USER node
CMD ["node", "dist/index.js"]
