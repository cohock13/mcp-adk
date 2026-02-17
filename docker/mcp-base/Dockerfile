# MCP Base Image - セキュアで軽量なベースコンテナ
FROM python:3.12-slim-bookworm

# 最小限のパッケージ（upgradeなし = 再現性確保）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        tini && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get clean

# 非rootユーザー（固定UID）
RUN useradd -u 10001 -m -s /bin/false mcpuser

# 依存関係インストール（バージョン固定）
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# 作業ディレクトリ
WORKDIR /app

# 非root実行
USER 10001:10001

# tini でPID 1問題を解決
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "server.py"]
