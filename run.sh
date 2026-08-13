#!/usr/bin/env bash
# 智能租房搜索系统 — macOS / Linux 启动脚本
# 用法:
#   chmod +x run.sh
#   ./run.sh              # 启动Web UI (app.py)
#   ./run.sh cli          # 仅计算可行域 (cli.py)
#   ./run.sh loop         # 完整多Agent Loop (run.py)
#   ./run.sh demo         # 运行演示流水线 (demo_zhengda_transit.py)

set -e
cd "$(dirname "$0")"

# 如果存在 .env 文件则加载
if [ -f .env ]; then
    set -a; source .env; set +a
fi

# 检查 python3
if ! command -v python3 &>/dev/null; then
    echo "错误: 未找到 python3，请先安装 Python 3.9+"
    exit 1
fi

# 检查虚拟环境
VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "首次运行，创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    pip install -q --upgrade pip
    if [ -f requirements.txt ]; then
        pip install -q -r requirements.txt
    fi
    echo "环境就绪。"
else
    source "$VENV_DIR/bin/activate"
fi

MODE="${1:-app}"

case "$MODE" in
    app)
        python app.py
        ;;
    cli)
        shift
        python cli.py "$@"
        ;;
    loop)
        shift
        python run.py "$@"
        ;;
    demo)
        python demo_zhengda_transit.py
        ;;
    *)
        echo "未知模式: $MODE (可选: app / cli / loop / demo)"
        exit 1
        ;;
esac
