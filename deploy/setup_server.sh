#!/bin/bash
# =============================================================================
# LoL 反转策略机器人 - 服务器一键安装脚本
# 在 VPS 上运行一次即可，之后自动在后台运行
# =============================================================================
set -e

echo "================================================"
echo "  LoL Bot 服务器安装脚本"
echo "================================================"

# ── 1. 系统依赖 ──────────────────────────────────────────────────────────────
echo ""
echo "▶ [1/5] 更新系统包..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git curl unzip screen

# ── 2. 创建项目目录 ──────────────────────────────────────────────────────────
echo ""
echo "▶ [2/5] 创建项目目录..."
mkdir -p /opt/lol-bot
cd /opt/lol-bot

# ── 3. Python 虚拟环境 ────────────────────────────────────────────────────────
echo ""
echo "▶ [3/5] 安装 Python 依赖..."
python3 -m venv venv
source venv/bin/activate
pip install -q --upgrade pip
pip install -q requests urllib3 python-dotenv py-clob-client

echo "  ✅ Python 依赖安装完成"

# ── 4. 配置 systemd 服务（开机自启）─────────────────────────────────────────
echo ""
echo "▶ [4/5] 配置后台服务..."
cat > /etc/systemd/system/lol-bot.service << 'EOF'
[Unit]
Description=LoL Reversal Strategy Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/lol-bot
EnvironmentFile=/opt/lol-bot/.env
ExecStart=/opt/lol-bot/venv/bin/python3 /opt/lol-bot/scripts/13_auto_trader.py
Restart=always
RestartSec=10
StandardOutput=append:/opt/lol-bot/data/bot.log
StandardError=append:/opt/lol-bot/data/bot.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable lol-bot
echo "  ✅ 服务配置完成（开机自启已启用）"

# ── 5. 创建数据目录 ──────────────────────────────────────────────────────────
echo ""
echo "▶ [5/5] 创建数据目录..."
mkdir -p /opt/lol-bot/data/game_winner_markets
mkdir -p /opt/lol-bot/data/rules

echo ""
echo "================================================"
echo "  ✅ 安装完成！"
echo ""
echo "  下一步：上传项目文件后运行："
echo "    systemctl start lol-bot   # 启动机器人"
echo "    systemctl status lol-bot  # 查看状态"
echo "    tail -f /opt/lol-bot/data/bot.log  # 实时查看日志"
echo "================================================"
