FROM node:24.19.0-alpine3.23 AS build
WORKDIR /app
COPY upstream/gateway-jurisprudencio/package.json upstream/gateway-jurisprudencio/package-lock.json ./
RUN npm ci --ignore-scripts
COPY upstream/gateway-jurisprudencio/tsconfig.json ./
COPY upstream/gateway-jurisprudencio/src ./src
COPY upstream/gateway-jurisprudencio/openapi.yaml ./openapi.yaml
RUN npm run check && npm run build && npm prune --omit=dev --ignore-scripts

FROM node:24.19.0-alpine3.23
ENV NODE_ENV=production
WORKDIR /app
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/dist ./dist
COPY --from=build --chown=node:node /app/openapi.yaml ./openapi.yaml
USER node
EXPOSE 3000
CMD ["node", "dist/server.js"]
