#!/bin/bash
# STDIO型MCPサーバーのエントリポイント

set -e

# stdoutはJSON-RPC専用、ログはstderrへ
exec python server.py
