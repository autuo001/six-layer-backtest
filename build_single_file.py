# -*- coding: utf-8 -*-
"""把 core + tools 组装成单个可执行的 .py 文件(带子命令)。

产出: six_layer_backtest.py —— 一个文件包含全部逻辑:
  core         核心回测(六层筛选+交易仿真+报告)
  entry_lab    事件级数据(候选特征+前瞻超额)
  forward_edge 分层检验+入场规则对比
  exit_lab     卖出参数×大盘层交叉测试
  loss_analysis 亏损归因
  freq_sweep   交易频率对照
  prefetch     并行预取候选股日线

用法: python3 build_single_file.py
"""
import os
import re

PKG = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(PKG, "core", "six_layer_v2.py")
TOOLS = ["prefetch.py", "entry_lab.py", "forward_edge.py", "exit_lab.py",
         "loss_analysis.py", "freq_sweep.py", "oos_split.py",
         "incremental_test.py", "stress_delist.py", "coverage_check.py"]
OUT = os.path.join(PKG, "six_layer_backtest.py")

HEADER = '''# -*- coding: utf-8 -*-
"""
六层选股回测框架 · 单文件版
=============================
把《个人炒股作战手册》的六层选股法与交易纪律做成可检验的回测框架。
单文件自带全部逻辑, 通过子命令调用:

  python3 six_layer_backtest.py core            # 核心回测(六层+交易仿真+报告+A/B+参数网格)
  python3 six_layer_backtest.py prefetch        # 预取候选股日线(联网, 三源回退, 断点续传)
  python3 six_layer_backtest.py entry_lab       # 事件级数据: 候选特征 + 建仓后5/20/60日超额
  python3 six_layer_backtest.py forward_edge    # 分层检验 + 入场规则对比 ← 改规则前先跑
  python3 six_layer_backtest.py exit_lab        # 卖出参数 × 大盘层 交叉测试
  python3 six_layer_backtest.py loss_analysis   # 亏损归因
  python3 six_layer_backtest.py freq_sweep      # 交易频率对照

数据位置(按优先级):
  1) 环境变量 SIXLAYER_DATA / SIXLAYER_CACHE / SIXLAYER_OUT
  2) 本文件同目录下的 data/parquet、cache、output
设 OFFLINE=1 表示不联网(缺数据的股票直接跳过)。

目录约定:
  data/parquet/daily/*.parquet   沪深300 成分股前复权日线
  data/parquet/yjbb.parquet      季度业绩报表
  data/parquet/index.parquet     沪深300 指数日线
  cache/                         候选股全历史日线缓存(prefetch 生成)
  output/                        报告与结果 CSV

核心结论(2018-2026, 含成本): 大盘层开 +12.1%/回撤-27.2%, 大盘层关 +23.6%/回撤-30.2%,
沪深300 同期 +6.6%/回撤-45.6%。参数依据见 core 子命令中的注释与 README。
已知乐观偏差: 业绩快照未来函数、幸存者偏差(退市股无数据)、参数敏感性大。

依赖: pip install akshare pandas numpy pyarrow
仅供个人研究, 不构成投资建议。
"""
'''

DISPATCH = '''

# ==================== 命令行入口 ====================
COMMANDS = {
    "core": ("核心回测(六层筛选+交易仿真+报告)", "run_core"),
    "prefetch": ("预取候选股日线(联网)", "main_prefetch"),
    "entry_lab": ("事件级数据: 候选特征+前瞻超额", "main_entry_lab"),
    "forward_edge": ("分层检验+入场规则对比", "main_forward_edge"),
    "exit_lab": ("卖出参数×大盘层交叉测试", "main_exit_lab"),
    "loss_analysis": ("亏损归因", "main_loss_analysis"),
    "freq_sweep": ("交易频率对照", "main_freq_sweep"),
    "oos_split": ("样本外切分: 2018-2023定参 → 2024-2026验证", "main_oos_split"),
    "incremental_test": ("增量检验: 六层过滤 vs 同池随机", "main_incremental_test"),
    "stress_delist": ("退市压力测试", "main_stress_delist"),
    "coverage_check": ("候选池覆盖率诊断", "main_coverage_check"),
}


def _usage():
    print("用法: python3 %s <command>" % os.path.basename(__file__))
    print("\\n可用命令:")
    for k, (desc, _) in COMMANDS.items():
        print("  %-14s %s" % (k, desc))


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _usage()
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print("未知命令: %s" % cmd)
        _usage()
        sys.exit(1)
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    fn = globals()[COMMANDS[cmd][1]]
    fn()
'''


def strip_tool(src, name):
    """去掉工具文件的模块级路径设置与 __main__ 块, 把 main() 改名, 并去掉对
    six_layer_v2 的模块前缀(合并到一个文件后同处一个命名空间)。"""
    src = re.sub(r"sys\.path\.insert\([^\n]*\)\n", "", src)
    # 删除 OUT_DIR 定义(含多行写法)
    lines, out, skip = src.splitlines(), [], False
    for ln in lines:
        if skip:
            if ln.rstrip().endswith(")"):
                skip = False
            continue
        if ln.startswith("OUT_DIR = "):
            if ln.count("(") == ln.count(")"):
                continue
            skip = True
            continue
        out.append(ln)
    src = "\n".join(out)
    src = re.sub(r"^import six_layer_v2 as m\n", "", src, flags=re.M)
    src = re.sub(r"\bm\.", "", src)          # m.CONFIG -> CONFIG 等
    src = re.sub(r"if __name__ == \"__main__\":\n    main\(\)\n?", "", src)
    src = re.sub(r"def main\(", "def main_%s(" % name, src)
    return src.strip()


def main():
    core = open(CORE).read()
    core = re.sub(r"if __name__ == \"__main__\":\n    run\(\)\n?", "", core)
    core = core.replace("def run():", "def run_core():")
    # 路径默认值改为"本文件同目录"
    core = core.replace(
        'PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # …/six_layer_backtest',
        'PKG_ROOT = os.path.dirname(os.path.abspath(__file__))   # 单文件所在目录')

    parts = [HEADER, core]
    for fn in TOOLS:
        name = os.path.splitext(fn)[0]
        src = open(os.path.join(PKG, "tools", fn)).read()
        parts.append("\n\n# ==================== %s ====================\n" % fn)
        parts.append(strip_tool(src, name))

    text = "\n".join(parts)
    text += DISPATCH
    with open(OUT, "w") as f:
        f.write(text)
    print("写出 %s (%.1f KB)" % (OUT, os.path.getsize(OUT) / 1024))


if __name__ == "__main__":
    main()
