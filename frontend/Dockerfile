FROM node:20-alpine AS dependencies

WORKDIR /app

# npm 源可替换：默认官方 registry；国内主机用
# --build-arg NPM_REGISTRY=https://registry.npmmirror.com 覆盖。
ARG NPM_REGISTRY=https://registry.npmjs.org

COPY package*.json ./
RUN npm ci --registry="${NPM_REGISTRY}"

FROM node:20-alpine AS builder

WORKDIR /app

ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL

COPY --from=dependencies /app/node_modules ./node_modules
COPY package*.json ./
COPY . .
RUN mkdir -p public && npm run build

FROM node:20-alpine AS runtime

WORKDIR /app

ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

ARG NPM_REGISTRY=https://registry.npmjs.org

COPY package*.json ./
RUN npm ci --omit=dev --registry="${NPM_REGISTRY}" && npm cache clean --force
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.mjs ./next.config.mjs

EXPOSE 3000

CMD ["npm", "run", "start", "--", "-H", "0.0.0.0"]
