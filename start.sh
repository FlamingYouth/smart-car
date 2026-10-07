#!/bin/bash
# Tesla微信通知系统启动脚本

set -e

echo "🚗 Tesla微信通知系统启动脚本"
echo "================================"

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "❌ 虚拟环境不存在，正在创建..."
    python3 -m venv venv
    echo "✅ 虚拟环境创建完成"
fi

# 激活虚拟环境
echo "🔧 激活虚拟环境..."
source venv/bin/activate

# 安装依赖
echo "📦 检查和安装依赖包..."
pip install -q -r requirements.txt

# 检查配置文件
CONFIG_FILE="config-prod.yaml"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "⚠️  生产配置文件 $CONFIG_FILE 不存在，使用默认配置 config.yaml"
    CONFIG_FILE="config.yaml"
fi

echo "📄 使用配置文件: $CONFIG_FILE"

# 运行测试（可选）
if [ "$1" = "--test" ]; then
    echo ""
    echo "🧪 运行系统测试..."
    echo "================================"
    
    echo "📱 测试所有启用的通知渠道..."
    python main.py -c "$CONFIG_FILE" --test-notifications
    
    echo ""
    echo "📡 测试MQTT连接..."
    python main.py -c "$CONFIG_FILE" --test-mqtt
    
    echo ""
    echo "🗄️ 测试数据库连接..."
    python main.py -c "$CONFIG_FILE" --test-db || echo "⚠️  数据库连接失败，请检查配置"
    
    echo ""
    echo "✅ 测试完成"
    exit 0
fi

# 正常启动系统
echo ""
echo "🚀 启动Tesla微信通知系统..."
echo "按 Ctrl+C 停止系统"
echo "================================"

# 启动主程序
python main.py -c "$CONFIG_FILE"