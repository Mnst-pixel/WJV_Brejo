FROM node:24.19.0-alpine3.23
ENV NODE_ENV=production
WORKDIR /app
COPY upstream/mcp-server/package.json upstream/mcp-server/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force
COPY --chown=node:node upstream/mcp-server/src ./src
USER node
EXPOSE 3002
CMD ["node", "src/server.mjs"]
