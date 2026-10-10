# -*- coding: utf-8 -*-
"""亏损归因分析: 把亏损拆成 选股能力 / 卖出纪律 / 成本 / 择时 四块。

用法: OFFLINE=1 python3 -u -m loss_analysis
"""
import os
import sys
from collections import defaultdict, deque

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
OUT_DIR = os.environ.get("SIXLAYER_OUT", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output"))
import six_layer_v2 as m


def load():
    idx = m.get_index_daily()
    cal = [d for d in m.get_trade_cal()
           if f"{m.START_YEAR}0101" <= d <= f"{m.END_YEAR}1231"]
    batches = m.build_batches(cal, idx, verbose=False)
    res = m.simulate(batches, cal)
    tr = pd.DataFrame(res["trades"], columns=["date", "code", "action", "price", "shares"])
    tr["date"] = pd.to_datetime(tr["date"])
    eq = pd.DataFrame(res["equity"], columns=["date", "equity"])
    eq["date"] = pd.to_datetime(eq["date"])
    return idx, cal, batches, tr, eq


def section(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def main():
    idx, cal, batches, tr, eq = load()
    buys = tr[tr.action == "buy"].reset_index(drop=True)
    sells = tr[tr.action != "buy"].reset_index(drop=True)
    idx_s = idx.set_index("date")["close"]

    # ---------- 1. 按卖出原因分解 ----------
    section("1. 卖出原因分解（金额口径，未扣费用）")
    rows = []
    for reason, g in sells.groupby("action"):
        doll = []
        for _, s in g.iterrows():
            b = buys[(buys.code == s.code) & (buys.date <= s.date)]
            if b.empty:
                continue
            bp = float(b.iloc[-1]["price"])
            doll.append((float(s["price"]) - bp) * float(s["shares"]))
        doll = np.array(doll)
        rows.append({"原因": reason, "腿数": len(g), "盈亏合计(元)": round(doll.sum()),
                     "平均每腿(元)": round(doll.mean()) if len(doll) else 0,
                     "胜率%": round((doll > 0).mean() * 100) if len(doll) else 0})
    df1 = pd.DataFrame(rows).sort_values("盈亏合计(元)")
    print(df1.to_string(index=False))

    # ---------- 2. 成本 ----------
    section("2. 交易成本（佣金+印花税+滑点）")
    buy_amt = (buys.price * buys.shares).sum()
    sell_amt = (sells.price * sells.shares).sum()
    comm = sum(max(a * m.CONFIG["commission"], m.CONFIG["min_commission"])
               for a in list(buys.price * buys.shares) + list(sells.price * sells.shares))
    tax = sell_amt * m.CONFIG["stamp_tax"]
    slip = (buy_amt + sell_amt) * m.CONFIG["slippage"]
    gross = 0.0
    for _, s in sells.iterrows():
        b = buys[(buys.code == s.code) & (buys.date <= s.date)]
        if not b.empty:
            gross += (float(s["price"]) - float(b.iloc[-1]["price"])) * float(s["shares"])
    net_change = eq.equity.iloc[-1] - eq.equity.iloc[0]
    print("买入总额 %.0f 元, 卖出总额 %.0f 元" % (buy_amt, sell_amt))
    print("毛盈亏(卖出价-买入价)     : %+.0f 元" % gross)
    print("佣金合计                 : -%.0f 元" % comm)
    print("印花税合计               : -%.0f 元" % tax)
    print("滑点合计(双边千1)        : -%.0f 元" % slip)
    print("净盈亏(权益变动, 含全部成本): %+.0f 元" % net_change)
    print("→ 成本占毛亏损的 %.0f%%（成本合计 %.0f 元）" % ((comm + tax + slip) / abs(gross) * 100, comm + tax + slip))

    # ---------- 3. 选股能力: 建仓后个股 vs 沪深300 ----------
    section("3. 选股能力：建仓后个股相对沪深300的超额（同期对比）")
    recs = []
    for _, b in buys.iterrows():
        code, d0 = b.code, b.date
        s = m.get_daily(code, m.INDEX_FETCH_START, f"{m.END_YEAR}1231")
        if s.empty:
            continue
        s = s.set_index("date")["close"]
        s = s[s.index >= d0]
        if len(s) < 2:
            continue
        ii = idx_s[idx_s.index >= d0]
        for off in (5, 20, 60):
            if len(s) > off and len(ii) > off:
                r = s.iloc[off] / float(b.price) - 1
                rb = ii.iloc[off] / ii.iloc[0] - 1
                recs.append({"code": code, "date": d0, "off": off,
                             "个股%": r * 100, "沪深300%": rb * 100, "超额%": (r - rb) * 100})
    fr = pd.DataFrame(recs)
    tab = fr.groupby("off")[["个股%", "沪深300%", "超额%"]].mean().round(2)
    tab["样本"] = fr.groupby("off").size()
    print(tab.to_string())
    print("→ 若超额均值≈0或为负, 说明六层选股没有选出跑赢指数的股票")

    # ---------- 4. 持仓路径: 最大浮盈/浮亏 ----------
    section("4. 持仓路径（建仓后到卖出前）")
    paths = []
    for _, b in buys.iterrows():
        code, d0 = b.code, b.date
        later = sells[(sells.code == code) & (sells.date > d0)]
        if later.empty:
            continue
        d1 = later.date.min()
        s = m.get_daily(code, m.INDEX_FETCH_START, f"{m.END_YEAR}1231")
        if s.empty:
            continue
        s = s[(s.date >= d0) & (s.date <= d1)]
        if s.empty:
            continue
        r = s["close"].values / float(b.price) - 1
        paths.append({"code": code, "entry": d0, "exit": d1,
                      "持有交易日": len(s),
                      "最大浮盈%": r.max() * 100, "最大浮亏%": r.min() * 100,
                      "最终%": r[-1] * 100})
    p = pd.DataFrame(paths)
    print(p[["持有交易日", "最大浮盈%", "最大浮亏%", "最终%"]].describe().round(2).to_string())
    print("最大浮盈>=9%%(第一止盈位)的比例: %.0f%%" % ((p["最大浮盈%"] >= 9).mean() * 100))
    print("最大浮亏<=-4%%(止损位)的比例  : %.0f%%" % ((p["最大浮亏%"] <= -4).mean() * 100))
    print("最终为正的比例                : %.0f%%" % ((p["最终%"] > 0).mean() * 100))

    # ---------- 5. 相对强度(第③层)是否有效 ----------
    section("5. 第③层相对强度排序是否有效（按入选RS分档看建仓后20日超额）")
    picks = []
    for bt in batches:
        for i, pk in enumerate(bt["picks"]):
            picks.append({"code": pk["code"], "rank": i, "rs": pk["rs"],
                          "date": pd.to_datetime(bt["signal_date"])})
    pk = pd.DataFrame(picks)
    fr20 = fr[fr.off == 20][["code", "date", "超额%"]]
    # 对齐: 信号日 → 实际建仓日(可能因高开>2%等原因缺失)
    buy_dates = buys[["code", "date"]].rename(columns={"date": "buy_date"})
    mg = pk.merge(buy_dates, on="code", how="inner")
    mg = mg[mg.buy_date >= mg.date]
    mg = mg.sort_values(["code", "date", "buy_date"]).groupby(["code", "date"], as_index=False).first()
    mg = mg.merge(fr20.rename(columns={"date": "buy_date"}), on=["code", "buy_date"], how="inner")
    if len(mg):
        mg["RS档"] = pd.cut(mg["rs"] * 100, [-100, 5, 15, 30, 1000],
                            labels=["<5%", "5-15%", "15-30%", ">30%"])
        print(mg.groupby("RS档", observed=True)["超额%"].agg(["count", "mean"]).round(2).to_string())
    print("→ 若高档超额不高于低档, 说明'买最强'这条没有预测力")

    # ---------- 6. 分年度 ----------
    section("6. 分年度（净收益 vs 基准）")
    eq["year"] = eq.date.dt.year
    idx_y = idx.set_index("date")["close"]
    rows = []
    prev = eq.equity.iloc[0]
    for y, g in eq.groupby("year"):
        r = g.equity.iloc[-1] / prev - 1
        ig = idx_y[idx_y.index.year == y]
        rb = ig.iloc[-1] / ig.iloc[0] - 1 if len(ig) > 1 else np.nan
        rows.append({"年份": y, "策略%": round(r * 100, 1),
                     "沪深300%": round(rb * 100, 1) if rb == rb else None,
                     "交易天数": len(g)})
        prev = g.equity.iloc[-1]
    print(pd.DataFrame(rows).to_string(index=False))

    # ---------- 7. 样本量与统计 ----------
    section("7. 样本量与统计意义")
    legs = len(sells)
    years = (eq.date.iloc[-1] - eq.date.iloc[0]).days / 365.25
    print("回测年数 %.1f, 建仓 %d 笔 (%.1f 笔/年), 平仓腿 %d 条" % (years, len(buys), len(buys) / years, legs))
    print("按腿等权期望 %+.2f%%, 年化 %.1f%%" %
          (0, ((eq.equity.iloc[-1] / eq.equity.iloc[0]) ** (1 / years) - 1) * 100))

    # ---------- 8. 反事实: 改止损/止盈/持有期 ----------
    section("8. 反事实测试：只改卖出参数（其余不变）")
    base = {k: m.CONFIG[k] for k in ("stop_loss_pct", "take_profit_1",
                                     "take_profit_2", "max_hold_days")}
    combos = [
        ("现状 止损-4% 止盈+9/+18 持有60日", {}),
        ("止损放宽到-6%", {"stop_loss_pct": 0.06}),
        ("止损放宽到-8%", {"stop_loss_pct": 0.08}),
        ("止损-8% + 止盈降到+6/+15", {"stop_loss_pct": 0.08,
                                 "take_profit_1": 0.06, "take_profit_2": 0.15}),
        ("止损-8% + 持有期缩到20日", {"stop_loss_pct": 0.08, "max_hold_days": 20}),
        ("止损-8% + 持有期拉长到120日", {"stop_loss_pct": 0.08, "max_hold_days": 120}),
    ]
    rows = []
    for name, over in combos:
        m.CONFIG.update(base)
        m.CONFIG.update(over)
        r = m.simulate(batches, cal)
        e = pd.DataFrame(r["equity"], columns=["date", "equity"])
        t = pd.DataFrame(r["trades"], columns=["date", "code", "action", "price", "shares"])
        sl = (t.action == "stop_loss").sum()
        rows.append({"卖出参数": name,
                     "总收益%": round((e.equity.iloc[-1] / m.CONFIG["initial_capital"] - 1) * 100, 1),
                     "最大回撤%": round(m.max_drawdown(e.equity) * 100, 1),
                     "止损腿数": sl, "卖出腿数": (t.action != "buy").sum()})
    m.CONFIG.update(base)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
