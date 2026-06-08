#!/bin/bash
# =============================================================================
# 本地运行此脚本，将项目文件同步到 VPS
# 用法: ./deploy/deploy.sh <服务器IP>
# 例如: ./deploy/deploy.sh 95.216.xxx.xxx
# =============================================================================

SERVER_IP="${1:-}"
if [ -z "$SERVER_IP" ]; then
    echo "用法: ./deploy/deploy.sh <服务器IP>"
    echo "例如: ./deploy/deploy.sh 95.216.123.456"
    exit 1
fi

REMOTE="root@${SERVER_IP}"
REMOTE_DIR="/opt/lol-bot"

echo "================================================"
echo "  部署到 $SERVER_IP"
echo "================================================"

# ── 上传项目文件 ──────────────────────────────────────────────────────────────
echo ""
echo "▶ 同步文件到服务器..."
rsync -avz --progress \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env' \
    --exclude='data/game_price_history/' \
    --exclude='output/' \
    --include='data/game_winner_markets/game_winner_markets.json' \
    --include='data/rules/' \
    --include='data/rules/trading_rules.json' \
    --include='data/rules/trading_rules.md' \
    --include='scripts/13_auto_trader.py' \
    --include='requirements_bot.txt' \
    . "${REMOTE}:${REMOTE_DIR}/"

# ── 检查 .env 是否存在 ────────────────────────────────────────────────────────
echo ""
if ssh "$REMOTE" "[ -f ${REMOTE_DIR}/.env ]"; then
    echo "✅ .env 文件已存在"
else
    echo "⚠️  .env 文件不存在，上传模板..."
    scp .env.example "${REMOTE}:${REMOTE_DIR}/.env"
    echo ""
    echo "❗ 重要：请填写服务器上的 .env 文件："
    echo "   ssh $REMOTE"
    echo "   nano /opt/lol-bot/.env"
fi

# ── 重启服务 ──────────────────────────────────────────────────────────────────
echo ""
echo "▶ 重启机器人服务..."
ssh "$REMOTE" "systemctl restart lol-bot && sleep 2 && systemctl status lol-bot --no-pager"

echo ""
echo "================================================"
echo "  ✅ 部署完成！"
echo ""
echo "  查看实时日志:"
echo "  ssh $REMOTE 'tail -f /opt/lol-bot/data/bot.log'"
echo "================================================"
