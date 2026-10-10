#!/bin/bash
# 一键跑完整套流程: 核心回测 + 三层检验工具
# 需要联网的步骤只有 prefetch.py（补数据）；其余可用 OFFLINE=1 离线跑。
set -e
cd "$(dirname "$0")"

echo "===== [1/5] 补数据（已缓存的会跳过；数据源限流时报错请稍后重试） ====="
python3 -u tools/prefetch.py || echo "  prefetch 未完成, 继续用已有缓存"

echo "===== [2/5] 核心回测 ====="
cd core && OFFLINE=1 python3 -u six_layer_v2.py | tee ../output/core_report.log
cd ..

echo "===== [3/5] 事件级数据 ====="
cd tools && OFFLINE=1 python3 -u entry_lab.py | tee ../output/entry_lab.log
cd ..

echo "===== [4/5] 分层检验 + 入场规则对比 ====="
cd tools && python3 -u forward_edge.py | tee ../output/forward_edge.log
cd ..

echo "===== [5/5] 亏损归因 ====="
cd tools && OFFLINE=1 python3 -u loss_analysis.py | tee ../output/loss_analysis.log
cd ..

echo "全部完成, 结果见 output/"
