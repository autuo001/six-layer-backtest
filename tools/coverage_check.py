# -*- coding: utf-8 -*-
"""覆盖率诊断: 候选池里有行情的比例有多少。

背景: 回测的候选池 = 业绩池(净利同比>=阈值, 去ST)。但免费数据源拿不到全部个股历史行情,
      缺的代码会被静默跳过。覆盖率不标注清楚, 结论就无法判断可信度。

输出: 每个报告期的 候选数 / 有行情数 / 覆盖率, 以及整体口径与"可补/不可补"拆分。
      结果写入 output/coverage.csv, 并导出可补清单 output/missing_codes.txt 供 prefetch 使用。

用法: OFFLINE=1 python3 -u coverage_check.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
OUT_DIR = os.environ.get(
    "SIXLAYER_OUT",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output"))
import six_layer_v2 as m


def main():
    y = m.load_yjbb_local()
    have = set(pd.read_parquet(os.path.join(m.V1_DATA, "daily_all.parquet"),
                               columns=["code"])["code"].unique())
    rows, need = [], set()
    for (year, period), g in sorted(y.items()):
        cand = g[g["profit_yoy"] >= m.CONFIG["min_profit_growth"]]
        if m.CONFIG["exclude_st"]:
            cand = cand[~cand["name"].astype(str).str.contains("ST|退", na=False)]
        codes = set(cand["code"])
        need |= codes
        rows.append({"报告期": "%s%s" % (year, period), "候选数": len(codes),
                     "有行情": len(codes & have),
                     "覆盖率%": round(100 * len(codes & have) / max(1, len(codes)), 1)})
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT_DIR, "coverage.csv"), index=False, encoding="utf-8-sig")

    def is_bse(c):
        return c[0] in "489"

    miss = sorted(need - have)
    fixable = [c for c in miss if not is_bse(c)]
    print("=" * 84)
    print("候选池覆盖率诊断（阈值 净利同比>=%s%%, 已去ST）" % m.CONFIG["min_profit_growth"])
    print("=" * 84)
    print("业绩池候选(全报告期去重): %d 只" % len(need))
    print("  有行情: %d 只 = %.1f%%" % (len(need & have), 100 * len(need & have) / len(need)))
    print("  缺行情: %d 只" % len(miss))
    print("     其中北交所(4xx/8xx/9xx, 免费源不支持): %d 只" % (len(miss) - len(fixable)))
    print("     可补沪深股: %d 只  → 已导出 output/missing_codes.txt" % len(fixable))
    print("\n分报告期覆盖率（尾部 12 期）:")
    print(df.tail(12).to_string(index=False))
    print("\n按批次加权的覆盖率: %.1f%%" %
          (100 * df["有行情"].sum() / df["候选数"].sum()))
    with open(os.path.join(OUT_DIR, "missing_codes.txt"), "w") as f:
        f.write("\n".join(fixable))
    print("\n提醒: 覆盖率低 + 缺失非随机 → 选股结论的解释力受限, 报告结论时必须标注该数字。")


if __name__ == "__main__":
    main()
