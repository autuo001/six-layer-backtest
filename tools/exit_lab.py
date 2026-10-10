# -*- coding: utf-8 -*-
"""卖出纪律 × 大盘层 交叉测试（在"均值回复入场"新规则下重做反事实）。

问题: 新入场买的是深回调/近期下跌股, 波动更大 → -4% 紧止损可能是主要杀手。
用法: OFFLINE=1 python3 -u -m exit_lab
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
OUT_DIR = os.environ.get("SIXLAYER_OUT", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output"))
import six_layer_v2 as m

BASE_KEYS = ("stop_loss_pct", "take_profit_1", "take_profit_2", "max_hold_days",
             "use_regime_filter")


def run(batches, cal, label, **over):
    for k in BASE_KEYS:
        m.CONFIG[k] = ORIG[k]
    m.CONFIG.update(over)
    res = m.simulate(batches, cal)
    eq = pd.DataFrame(res["equity"], columns=["date", "equity"])
    tr = pd.DataFrame(res["trades"], columns=["date", "code", "action", "price", "shares"])
    returns = []
    buys = tr[tr.action == "buy"]
    for _, s in tr[tr.action != "buy"].iterrows():
        b = buys[(buys.code == s.code) & (buys.date <= s.date)]
        if not b.empty:
            returns.append((s.price - b.iloc[-1].price) * s.shares)
    gross = sum(returns)
    return {
        "参数": label,
        "总收益%": round((eq.equity.iloc[-1] / m.CONFIG["initial_capital"] - 1) * 100, 1),
        "最大回撤%": round(m.max_drawdown(eq.equity) * 100, 1),
        "买入笔数": len(buys), "卖出腿数": len(tr) - len(buys),
        "止损腿数": int((tr.action == "stop_loss").sum()),
        "毛盈亏(元)": round(gross),
        "年化%": round(((eq.equity.iloc[-1] / m.CONFIG["initial_capital"])
                        ** (1 / 8.7) - 1) * 100, 1),
    }


ORIG = {k: m.CONFIG[k] for k in BASE_KEYS}


def main():
    idx = m.get_index_daily()
    cal = [d for d in m.get_trade_cal()
           if f"{m.START_YEAR}0101" <= d <= f"{m.END_YEAR}1231"]

    rows = []
    for regime in (True, False):
        tag = "大盘层开" if regime else "大盘层关"
        # 关键: 批次必须在对应的 regime 设置下重建, 否则 regime_ok 用的是旧值
        m.CONFIG["use_regime_filter"] = regime
        batches = m.build_batches(cal, idx, verbose=False)
        rows.append(run(batches, cal, f"{tag} | 止损-4% 止盈9/18 持有60",
                        use_regime_filter=regime))
        rows.append(run(batches, cal, f"{tag} | 止损-8%",
                        use_regime_filter=regime, stop_loss_pct=0.08))
        rows.append(run(batches, cal, f"{tag} | 止损-12%",
                        use_regime_filter=regime, stop_loss_pct=0.12))
        rows.append(run(batches, cal, f"{tag} | 不止损(仅时间+止盈)",
                        use_regime_filter=regime, stop_loss_pct=0.99))
        rows.append(run(batches, cal, f"{tag} | 止损-12% + 持有120日 + 止盈12/25",
                        use_regime_filter=regime, stop_loss_pct=0.12,
                        max_hold_days=120, take_profit_1=0.12, take_profit_2=0.25))
        rows.append(run(batches, cal, f"{tag} | 止损-12% + 持有20日",
                        use_regime_filter=regime, stop_loss_pct=0.12,
                        max_hold_days=20))

    # 在最优点附近做稳健性扫描（只测大盘层关: 该入场逻辑偏好在弱市买入）
    m.CONFIG["use_regime_filter"] = False
    batches = m.build_batches(cal, idx, verbose=False)
    for st in (0.10, 0.12, 0.15):
        for hold in (90, 120, 180):
            rows.append(run(batches, cal, f"稳健性 | 止损-{int(st*100)}% 持有{hold}日 止盈12/25",
                            use_regime_filter=False, stop_loss_pct=st,
                            max_hold_days=hold, take_profit_1=0.12, take_profit_2=0.25))
    # 不止损变体: 持有期 × 止盈位
    for hold in (60, 90, 120, 180):
        for tp1, tp2 in ((0.09, 0.18), (0.12, 0.25)):
            rows.append(run(batches, cal,
                            f"不止损 | 持有{hold}日 止盈{int(tp1*100)}/{int(tp2*100)}",
                            use_regime_filter=False, stop_loss_pct=0.99,
                            max_hold_days=hold, take_profit_1=tp1, take_profit_2=tp2))
    for k in BASE_KEYS:
        m.CONFIG[k] = ORIG[k]
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    df.to_csv(os.path.join(OUT_DIR, "exit_lab.csv"), index=False, encoding="utf-8-sig")
    print("\n已存 exit_lab.csv")


if __name__ == "__main__":
    main()
