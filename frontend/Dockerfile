FROM node:24-alpine AS dependencies

WORKDIR /app

# npm 源可替换：默认官方 registry；国内主机用
# --build-arg NPM_REGISTRY=https://registry.npmmirror.com 覆盖。
ARG NPM_REGISTRY=https://registry.npmjs.org

COPY package*.json ./
RUN npm ci --registry="${NPM_REGISTRY}"

FROM node:24-alpine AS builder

WORKDIR /app

ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL

# P2: the frontend must report the same release identity as the API/worker/beat, otherwise the
# version banner cannot prove the release is internally consistent. "unknown" stays visible on
# purpose: the release gate rejects it instead of showing a plausible-looking wrong commit.
ARG NEXT_PUBLIC_APP_COMMIT=unknown
ARG NEXT_PUBLIC_BUILD_TIME=unknown
ARG NEXT_PUBLIC_SCHEMA_HEAD=
ENV NEXT_PUBLIC_APP_COMMIT=$NEXT_PUBLIC_APP_COMMIT
ENV NEXT_PUBLIC_BUILD_TIME=$NEXT_PUBLIC_BUILD_TIME
ENV NEXT_PUBLIC_SCHEMA_HEAD=$NEXT_PUBLIC_SCHEMA_HEAD

COPY --from=dependencies /app/node_modules ./node_modules
COPY package*.json ./
COPY . .
RUN mkdir -p public && npm run build

FROM node:24-alpine AS runtime

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
