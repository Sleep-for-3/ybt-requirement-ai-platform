FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 依赖索引可替换：默认官方 PyPI；国内主机（无法稳定访问 pypi.org）
# 用 --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple 覆盖。
ARG PIP_INDEX_URL=https://pypi.org/simple

# B18/P2: baked into the image as a *fallback* for `app.services.version_info`. Runtime environment
# still wins; without a baked value an image started outside compose would report a blank identity.
# It is written after `COPY . .` below so the packaged file cannot overwrite it.
ARG APP_COMMIT=unknown
ARG BUILD_TIME=unknown
# W01/P1: install from the *locked* pin set so a rebuild cannot drift.  requirements.txt stays the
# declared-range source of truth for humans; the lock is what actually ships.
COPY requirements.txt requirements.lock.txt ./
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements.lock.txt \
 && pip check

COPY . .

# B18/P2: the build stamp must be the last word, otherwise a checked-in build-info.json silently
# overrides the identity the release script passed to `docker build`.
RUN printf '{"app_commit": "%s", "build_time": "%s"}\n' "$APP_COMMIT" "$BUILD_TIME" > /app/build-info.json

EXPOSE 8000

# Schema upgrades run in the one-shot ``migrate`` Compose service so API,
# Worker and Beat can never start against a half-migrated database.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
