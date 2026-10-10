# -*- coding: utf-8 -*-
"""样本外(OOS)切分验证: 2018-2023 定参 → 2024-2026 只验一次。

做法:
  1) 在 IS(2018-2023) 上用一个小网格挑最优参数(按 IS 总收益, 回撤做约束)
  2) 用挑出的参数在 OOS(2024-2026) 上跑一次, 不再回头改
  3) 同时给出"当前默认参数"的 IS/OOS, 作为对照(默认参数是在全样本上定的, 已被污染)
  4) 额外给出"IS最优但只在OOS见效"与"IS最优且OOS仍为正"的比例, 检验稳健性

用法: OFFLINE=1 python3 -u oos_split.py
"""
import os
import sys
import time
from itertools import product

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
OUT_DIR = os.environ.get(
    "SIXLAYER_OUT",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output"))
import six_layer_v2 as m

IS_END = "20231231"
OOS_START = "20240101"

GRID = {
    "stop_loss_pct": [0.04, 0.08, 0.15],
    "max_hold_days": [60, 90],
    "min_profit_growth": [30, 50, 80],
    "pullback_min": [10, 20],
    "use_regime_filter": [False, True],
}
KEYS = list(GRID)


def run_one(cal_all, index_df, cal_is, cal_oos, **over):
    saved = {k: m.CONFIG.get(k) for k in over}
    m.CONFIG.update(over)
    try:
        batches = m.build_batches(cal_all, index_df, verbose=False)
        out = {}
        for tag, cal in (("IS", cal_is), ("OOS", cal_oos)):
            res = m.simulate(batches, cal, liquidate_at_end=True)
            eq = pd.DataFrame(res["equity"], columns=["date", "equity"])
            tr = pd.DataFrame(res["trades"], columns=["date", "code", "action", "price", "shares"])
            ret = eq.equity.iloc[-1] / m.CONFIG["initial_capital"] - 1
            buys = tr[tr.action == "buy"]
            gross = 0.0
            for _, s in tr[tr.action != "buy"].iterrows():
                b = buys[(buys.code == s.code) & (buys.date <= s.date)]
                if not b.empty:
                    gross += (s.price - b.iloc[-1].price) * s.shares
            out[tag] = {
                "收益%": ret * 100,
                "回撤%": m.max_drawdown(eq.equity) * 100,
                "买入笔数": len(buys),
                "毛盈亏": gross,
            }
        return out
    finally:
        m.CONFIG.update(saved)


def main():
    t0 = time.time()
    index_df = m.get_index_daily()
    cal_all = [d for d in m.get_trade_cal()
               if f"{m.START_YEAR}0101" <= d <= f"{m.END_YEAR}1231"]
    cal_is = [d for d in cal_all if d <= IS_END]
    cal_oos = [d for d in cal_all if d >= OOS_START]
    print("IS 交易日 %d (%s~%s), OOS 交易日 %d (%s~%s)" %
          (len(cal_is), cal_is[0], cal_is[-1], len(cal_oos), cal_oos[0], cal_oos[-1]))

    default = {k: m.CONFIG[k] for k in KEYS}
    print("当前默认参数: %s" % default)

    rows = []
    combos = list(product(*[GRID[k] for k in KEYS]))
    for i, combo in enumerate(combos, 1):
        cfg = dict(zip(KEYS, combo))
        r = run_one(cal_all, index_df, cal_is, cal_oos, **cfg)
        rows.append({**cfg, "IS收益%": round(r["IS"]["收益%"], 1),
                     "IS回撤%": round(r["IS"]["回撤%"], 1), "IS笔数": r["IS"]["买入笔数"],
                     "OOS收益%": round(r["OOS"]["收益%"], 1),
                     "OOS回撤%": round(r["OOS"]["回撤%"], 1), "OOS笔数": r["OOS"]["买入笔数"]})
        if i % 12 == 0:
            print("  已跑 %d/%d 组 (%.0fs)" % (i, len(combos), time.time() - t0), flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT_DIR, "oos_grid.csv"), index=False, encoding="utf-8-sig")

    print("\n" + "=" * 100)
    print("一、IS(2018-2023) 前 10 名 与它们的 OOS(2024-2026) 表现")
    print("=" * 100)
    top = df.sort_values("IS收益%", ascending=False).head(10)
    print(top.to_string(index=False))

    best_is = df.sort_values("IS收益%", ascending=False).iloc[0]
    print("\nIS 最优参数: %s  → IS %+.1f%% / OOS %+.1f%%" %
          ({k: best_is[k] for k in KEYS}, best_is["IS收益%"], best_is["OOS收益%"]))

    print("\n" + "=" * 100)
    print("二、稳健性统计（全网格 %d 组）" % len(df))
    print("=" * 100)
    print("IS 收益中位数 %+.1f%%, OOS 收益中位数 %+.1f%%" %
          (df["IS收益%"].median(), df["OOS收益%"].median()))
    print("IS 为正的比例 %.0f%%, OOS 为正的比例 %.0f%%" %
          ((df["IS收益%"] > 0).mean() * 100, (df["OOS收益%"] > 0).mean() * 100))
    print("IS 与 OOS 收益的相关系数: %.2f  （接近0说明IS挑参数对OOS没有预测力）" %
          df["IS收益%"].corr(df["OOS收益%"]))
    top20 = df.sort_values("IS收益%", ascending=False).head(max(5, len(df) // 5))
    print("IS 前20%% 的组, 其 OOS 为正比例 %.0f%%, OOS 中位数 %+.1f%%" %
          ((top20["OOS收益%"] > 0).mean() * 100, top20["OOS收益%"].median()))

    print("\n" + "=" * 100)
    print("三、当前默认参数 vs IS最优参数")
    print("=" * 100)
    d = run_one(cal_all, index_df, cal_is, cal_oos, **default)
    print("默认参数 %s" % default)
    print("  IS : %+.1f%%  回撤 %.1f%%  %d 笔" % (d["IS"]["收益%"], d["IS"]["回撤%"], d["IS"]["买入笔数"]))
    print("  OOS: %+.1f%%  回撤 %.1f%%  %d 笔" % (d["OOS"]["收益%"], d["OOS"]["回撤%"], d["OOS"]["买入笔数"]))
    print("IS最优 %s" % {k: best_is[k] for k in KEYS})
    print("  IS : %+.1f%%  回撤 %.1f%%  %d 笔" % (best_is["IS收益%"], best_is["IS回撤%"], best_is["IS笔数"]))
    print("  OOS: %+.1f%%  回撤 %.1f%%  %d 笔" % (best_is["OOS收益%"], best_is["OOS回撤%"], best_is["OOS笔数"]))
    print("\n总用时 %.0f 秒" % (time.time() - t0))


if __name__ == "__main__":
    main()
