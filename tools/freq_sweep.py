# -*- coding: utf-8 -*-
"""交易频率对照: 同一套六层逻辑, 只改"频率相关"参数, 看笔数与绩效如何变化。

用法: OFFLINE=1 python3 -u -m freq_sweep
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
OUT_DIR = os.environ.get("SIXLAYER_OUT", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output"))
import six_layer_v2 as m
import pandas as pd


def run_config(name, **over):
    base = {
        "report_periods": ["0630", "0930"],
        "max_positions": 3,
        "position_pct": 0.30,
        "pullback_min": 5,
        "pullback_max": 25,
        "min_profit_growth": 50,
        "regime_ma": 250,
        "use_regime_filter": True,
        "max_candidates_per_batch": 0,
        "strict_disclosure": False,
    }
    base.update(over)
    m.CONFIG.update(base)

    index_df = m.get_index_daily()
    # regime_ma 变化需要重算均线
    index_df["ma"] = index_df["close"].rolling(m.CONFIG["regime_ma"]).mean()
    cal = [d for d in m.get_trade_cal() if f"{m.START_YEAR}0101" <= d <= f"{m.END_YEAR}1231"]

    batches = m.build_batches(cal, index_df, verbose=False)
    n_pick = sum(len(b["picks"]) for b in batches)
    n_skip = sum(1 for b in batches if not b["regime_ok"])
    res = m.simulate(batches, cal)
    tr = pd.DataFrame(res["trades"], columns=["date", "code", "action", "price", "shares"])
    eq = pd.DataFrame(res["equity"], columns=["date", "equity"])
    total = eq["equity"].iloc[-1] / m.CONFIG["initial_capital"] - 1
    mdd = m.max_drawdown(eq["equity"])

    buys = tr[tr["action"] == "buy"]
    sells = tr[tr["action"] != "buy"]
    pnl = []
    for _, s in sells.iterrows():
        b = buys[(buys["code"] == s["code"]) & (buys["date"] <= s["date"])]
        if not b.empty:
            pnl.append(s["price"] / b.iloc[-1]["price"] - 1)
    pnl = pd.Series(pnl)
    win = (pnl > 0).mean() * 100 if len(pnl) else float("nan")
    pl = abs(pnl[pnl > 0].mean() / pnl[pnl <= 0].mean()) if len(pnl) and (pnl <= 0).any() else float("nan")
    return {
        "配置": name,
        "批次数": len(batches),
        "空仓批次": n_skip,
        "入选次数": n_pick,
        "买入笔数": len(buys),
        "卖出笔数": len(sells),
        "总收益%": round(total * 100, 1),
        "最大回撤%": round(mdd * 100, 1),
        "胜率%": round(win, 0),
        "盈亏比": round(pl, 2),
    }


def main():
    rows = []
    rows.append(run_config("A 原配置(2批/3仓/回撤5-25/阈值50)"))
    rows.append(run_config("B 高频(4批/5仓/回撤3-40/阈值50)",
                           report_periods=["0331", "0630", "0930", "1231"],
                           max_positions=5, position_pct=0.20,
                           pullback_min=3, pullback_max=40))
    rows.append(run_config("C B+阈值降到30",
                           report_periods=["0331", "0630", "0930", "1231"],
                           max_positions=5, position_pct=0.20,
                           pullback_min=3, pullback_max=40,
                           min_profit_growth=30))
    rows.append(run_config("D C+大盘层放宽到MA120",
                           report_periods=["0331", "0630", "0930", "1231"],
                           max_positions=5, position_pct=0.20,
                           pullback_min=3, pullback_max=40,
                           min_profit_growth=30, regime_ma=120))
    rows.append(run_config("E D+8仓",
                           report_periods=["0331", "0630", "0930", "1231"],
                           max_positions=8, position_pct=0.125,
                           pullback_min=3, pullback_max=40,
                           min_profit_growth=30, regime_ma=120))
    rows.append(run_config("F 高频8仓但保住阈值50(手册口径)",
                           report_periods=["0331", "0630", "0930", "1231"],
                           max_positions=8, position_pct=0.125,
                           pullback_min=3, pullback_max=40,
                           min_profit_growth=50, regime_ma=120))
    df = pd.DataFrame(rows)
    print("\n" + "=" * 100)
    print("交易频率对照（同一套六层逻辑，仅改频率相关参数；行情为本地缓存）")
    print("=" * 100)
    print(df.to_string(index=False))
    df.to_csv(os.path.join(OUT_DIR, "freq_sweep.csv"), index=False, encoding="utf-8-sig")
    print("\n已存 freq_sweep.csv")


if __name__ == "__main__":
    main()
