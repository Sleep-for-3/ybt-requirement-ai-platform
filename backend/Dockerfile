FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 依赖索引可替换：默认官方 PyPI；国内主机（无法稳定访问 pypi.org）
# 用 --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple 覆盖。
ARG PIP_INDEX_URL=https://pypi.org/simple

COPY requirements.txt .
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements.txt

COPY . .

EXPOSE 8000

# Schema upgrades run in the one-shot ``migrate`` Compose service so API,
# Worker and Beat can never start against a half-migrated database.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
