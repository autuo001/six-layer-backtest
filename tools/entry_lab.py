# -*- coding: utf-8 -*-
"""入场信号检验台: 对每个候选股算建仓时的特征 + 建仓后 5/20/60 日相对沪深300超额。

目的: 用数据回答"哪一层有预测力、往哪个方向调", 而不是靠猜。
     产出 v2 事件级数据 candidates.csv, 供 forward_edge.py 做分层与规则对比。

用法: OFFLINE=1 python3 -u -m entry_lab
"""
import bisect
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
OUT_DIR = os.environ.get("SIXLAYER_OUT", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output"))
import six_layer_v2 as m

OUT = os.path.join(OUT_DIR, "candidates.csv")


def main():
    idx = m.get_index_daily()
    idx_dates = list(idx["date"])
    idx_close = idx["close"].values
    cal = [d for d in m.get_trade_cal()
           if f"{m.START_YEAR}0101" <= d <= f"{m.END_YEAR}1231"]

    rows = []
    n_batches = 0
    for year in range(m.START_YEAR, m.END_YEAR + 1):
        for period in m.CONFIG["report_periods"]:
            sd = m.batch_signal_date(cal, year, period)
            if not sd:
                continue
            n_batches += 1
            rep = m.get_report_data(year, period)
            if rep.empty:
                continue
            df = rep[rep["profit_yoy"] >= m.CONFIG["min_profit_growth"]]
            if m.CONFIG["exclude_st"]:
                df = df[~df["name"].astype(str).str.contains("ST|退", na=False)]
            sdt = pd.to_datetime(sd)
            i_idx = bisect.bisect_right(idx_dates, sdt) - 1
            if i_idx < 20:
                continue
            for _, r in df.iterrows():
                code = r["code"]
                full = m.load_full_daily(code)
                if full.empty:
                    continue
                dates = list(full["date"])
                k = bisect.bisect_right(dates, sdt) - 1
                if k < 130:
                    continue
                c = full["close"].values
                v = full["volume"].values
                px = c[k]
                if px <= 0:
                    continue
                high60 = c[k - 59:k + 1].max()
                pullback = (high60 - px) / high60 * 100
                gain60 = (px / c[k - 60] - 1) * 100
                # 相对强度: 近20日 个股 - 指数
                r_stk = px / c[k - 20] - 1
                j = i_idx
                r_idx = idx_close[j] / idx_close[j - 20] - 1
                rs = (r_stk - r_idx) * 100
                ma10 = c[k - 9:k + 1].mean()
                vol_ratio = v[k] / v[k - 19:k + 1].mean()
                ret5 = (px / c[k - 5] - 1) * 100
                # 前瞻收益(用建仓日开盘近似: 用收盘到未来收盘, 与回测口径略有差异, 用于比较相对优劣)
                fwd = {}
                for off in (5, 20, 60):
                    if k + off < len(c):
                        rf = c[k + off] / px - 1
                        if i_idx + off < len(idx_close):
                            rb = idx_close[i_idx + off] / idx_close[i_idx] - 1
                        else:
                            rb = np.nan
                        fwd["fwd%d" % off] = rf * 100
                        fwd["exc%d" % off] = (rf - rb) * 100
                rows.append({"year": year, "period": period,
                             "signal_date": pd.to_datetime(sd).strftime("%Y-%m-%d"),
                             "code": code, "profit_yoy": r["profit_yoy"],
                             "rs20": rs, "pullback": pullback, "gain60": gain60,
                             "vol_ratio": vol_ratio, "ret5": ret5,
                             "above_ma10": px > ma10,
                             "idx_above_ma": (idx_close[i_idx] > idx["ma"].values[i_idx])
                             if m.CONFIG["regime_ma"] else True,
                             **fwd})
            print("  %s%s 完成, 累计候选 %d" % (year, period, len(rows)), flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")
    print("\n写出 %s: %d 行, %d 个批次" % (OUT, len(out), n_batches))


if __name__ == "__main__":
    main()
