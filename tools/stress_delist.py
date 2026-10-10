# -*- coding: utf-8 -*-
"""退市压力测试: 给"长期无行情按最后价平仓"加惩罚档位, 看结论是否翻转。

三层压力:
  A. 现实核查: 真实回测里触发了多少次"停牌>90日强制平仓"(由于数据只含存续股, 大概是0)
  B. 强制平仓惩罚档: 0% / -30% / -50% / -70% (对真实发生的强平事件打折)
  C. 合成退市注入: 每笔建仓以 p 的概率被判"退市", 亏 delist_loss;
     p ∈ {2%, 5%, 10%}, delist_loss ∈ {50%, 100%}, 每个组合跑 5 个随机种子取均值
     并给出: 结论翻转需要多少次退市(以单笔仓位 12.5% 计)

用法: OFFLINE=1 python3 -u stress_delist.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
OUT_DIR = os.environ.get(
    "SIXLAYER_OUT",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output"))
import six_layer_v2 as m

SAVE = ("delist_haircut", "delist_prob", "delist_loss", "stress_seed",
        "use_regime_filter")


def summarize(res, label):
    eq = pd.DataFrame(res["equity"], columns=["date", "equity"])
    tr = pd.DataFrame(res["trades"], columns=["date", "code", "action", "price", "shares"])
    ret = eq.equity.iloc[-1] / m.CONFIG["initial_capital"] - 1
    return {"场景": label,
            "总收益%": round(ret * 100, 1),
            "最大回撤%": round(m.max_drawdown(eq.equity) * 100, 1),
            "买入笔数": int((tr.action == "buy").sum()),
            "强平笔数": int((tr.action == "delist_exit").sum()),
            "注入退市笔数": res.get("n_doomed", 0)}


def main():
    idx = m.get_index_daily()
    cal = [d for d in m.get_trade_cal()
           if f"{m.START_YEAR}0101" <= d <= f"{m.END_YEAR}1231"]
    saved = {k: m.CONFIG[k] for k in SAVE}

    batches_off = None
    batches_on = None
    rows = []

    # A + B: 真实强平次数 与 惩罚档位(分别在大盘层开/关两种设置下)
    batches_by_regime = {}
    for regime in (False, True):
        m.CONFIG["use_regime_filter"] = regime
        batches = m.build_batches(cal, idx, verbose=False)
        batches_by_regime[regime] = batches
        tag = "大盘层开" if regime else "大盘层关"
        for hc in (0.0, 0.3, 0.5, 0.7):
            m.CONFIG["delist_haircut"] = hc
            m.CONFIG["delist_prob"] = 0.0
            res = m.simulate(batches, cal, liquidate_at_end=True)
            rows.append(summarize(res, "%s | 真实强平惩罚 -%.0f%%" % (tag, hc * 100)))
        m.CONFIG["delist_haircut"] = 0.0

    dfB = pd.DataFrame(rows)
    print("=" * 96)
    print("A/B. 真实强平事件与惩罚档（现实核查）")
    print("=" * 96)
    print(dfB.to_string(index=False))
    if (dfB["强平笔数"] == 0).any():
        print("\n注意: 强平笔数为 0 → 我们的行情库只含存续股票, 数据里根本不存在退市样本,")
        print("      所以真实惩罚档没有效果; 退市风险只能用下面的合成注入来压力测试。")

    # C: 合成退市注入（两种大盘层设置各跑一遍, 明确标注）
    print("\n" + "=" * 96)
    print("C. 合成退市注入（每笔建仓按概率被判退市, 亏 delist_loss; 5 个种子取均值）")
    print("=" * 96)
    rows = []
    base_ret = {}
    for regime in (False, True):
        tag = "大盘层开" if regime else "大盘层关"
        batches = batches_by_regime[regime]
        for p in (0.0, 0.02, 0.05, 0.10):
            for loss in (0.5, 1.0):
                rets, mdds, doomed = [], [], []
                for seed in range(5):
                    m.CONFIG["delist_prob"] = p
                    m.CONFIG["delist_loss"] = loss
                    m.CONFIG["stress_seed"] = 20261010 + seed
                    res = m.simulate(batches, cal, liquidate_at_end=True)
                    eq = pd.DataFrame(res["equity"], columns=["date", "equity"])
                    rets.append(eq.equity.iloc[-1] / m.CONFIG["initial_capital"] - 1)
                    mdds.append(m.max_drawdown(eq.equity))
                    doomed.append(res["n_doomed"])
                if p == 0.0:
                    base_ret[regime] = float(np.mean(rets))
                rows.append({"大盘层": tag,
                             "退市概率": "%.0f%%" % (p * 100),
                             "单笔损失": "%.0f%%" % (loss * 100),
                             "总收益%(均值)": round(float(np.mean(rets)) * 100, 1),
                             "收益区间": "%.1f~%.1f" % (min(rets) * 100, max(rets) * 100),
                             "最大回撤%(均值)": round(float(np.mean(mdds)) * 100, 1),
                             "平均退市笔数": round(float(np.mean(doomed)), 1)})
    dfC = pd.DataFrame(rows)
    print(dfC.to_string(index=False))
    dfC.to_csv(os.path.join(OUT_DIR, "stress_delist.csv"), index=False, encoding="utf-8-sig")

    print("\n结论翻转门槛（按单笔仓位 12.5% 全损计算）:")
    for regime, r0 in base_ret.items():
        n = int(np.ceil((r0 * 100) / 12.5)) if r0 > 0 else 0
        print("  %s: 基线 %+.1f%% → 需要约 %d 笔全损退市把结论打成负"
              % ("大盘层关" if not regime else "大盘层开", r0 * 100, n))
    print("而 5%% 概率 ≈ 每 20 笔建仓 1 笔退市; 本回测 77~173 笔建仓 → 约 4~9 笔。")

    m.CONFIG.update(saved)


if __name__ == "__main__":
    main()
