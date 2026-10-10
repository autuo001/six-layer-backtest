# -*- coding: utf-8 -*-
"""基于 entry_lab 产出的事件数据, 检验各层预测力并对比候选入场规则。

用法: python3 -u -m forward_edge
"""
import os

import numpy as np
import pandas as pd

OUT_DIR = os.environ.get(
    "SIXLAYER_OUT",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output"))

pd.set_option("display.width", 200)


def tstat(x):
    x = pd.Series(x).dropna()
    if len(x) < 3 or x.std() == 0:
        return np.nan
    return x.mean() / (x.std() / np.sqrt(len(x)))


def main():
    df = pd.read_csv(os.path.join(OUT_DIR, "candidates.csv"))
    df = df.dropna(subset=["exc20", "exc60"])
    print("样本: %d 个候选事件, %d 个批次, %d~%d" %
          (len(df), df.signal_date.nunique(), df.year.min(), df.year.max()))

    print("\n" + "=" * 96)
    print("一、单特征分层（指标=建仓后相对沪深300超额均值, 单位%）")
    print("=" * 96)

    def bucket(col, bins, labels):
        g = df.copy()
        g["档"] = pd.cut(g[col], bins, labels=labels)
        t = g.groupby("档", observed=True).agg(
            样本=("exc20", "size"), 超额5日=("exc5", "mean"), 超额20日=("exc20", "mean"),
            超额60日=("exc60", "mean"), 胜率20日=("exc20", lambda s: (s > 0).mean() * 100))
        t["t值20日"] = g.groupby("档", observed=True)["exc20"].apply(tstat)
        return t.round(2)

    print("\n【RS 相对强度(第③层)】20日超额越高越好? ")
    print(bucket("rs20", [-100, -10, 0, 10, 20, 40, 1000],
                 ["<-10%", "-10~0", "0~10", "10~20", "20~40", ">40"]).to_string())

    print("\n【位置: 距60日高点回撤(第②层)】")
    print(bucket("pullback", [-100, 0, 5, 10, 20, 30, 100],
                 ["<0(新高)", "0~5", "5~10", "10~20", "20~30", ">30"]).to_string())

    print("\n【量比(20日均量)】")
    print(bucket("vol_ratio", [0, 0.8, 1.2, 2, 3, 100],
                 ["<0.8", "0.8~1.2", "1.2~2", "2~3", ">3"]).to_string())

    print("\n【近5日涨幅】")
    print(bucket("ret5", [-100, -5, 0, 5, 10, 100],
                 ["<-5%", "-5~0", "0~5", "5~10", ">10"]).to_string())

    print("\n【业绩增速】")
    print(bucket("profit_yoy", [50, 80, 150, 300, 10000],
                 ["50~80", "80~150", "150~300", ">300"]).to_string())

    print("\n【60日涨幅】")
    print(bucket("gain60", [-100, -10, 0, 20, 50, 10000],
                 ["<-10%", "-10~0", "0~20", "20~50", ">50"]).to_string())

    print("\n【是否站上MA10 / 大盘环境】")
    for col in ("above_ma10", "idx_above_ma"):
        g = df.groupby(col).agg(样本=("exc20", "size"), 超额20日=("exc20", "mean"),
                                超额60日=("exc60", "mean"),
                                胜率20日=("exc20", lambda s: (s > 0).mean() * 100)).round(2)
        print("\n%s:\n%s" % (col, g.to_string()))

    # ---------- 二、规则对比 ----------
    print("\n" + "=" * 96)
    print("二、候选入场规则对比（每批次取N=8只, 等权；指标为这些『实际会被选中』股票的建仓后超额）")
    print("=" * 96)

    N = 8

    def pick(g, sort_col=None, ascending=False, head=None):
        if sort_col:
            g = g.sort_values(sort_col, ascending=ascending)
        return g.head(head or N)

    rules = {}

    def add_rule(name, fn):
        parts = []
        for _, g in df.groupby("signal_date"):
            sel = fn(g)
            if len(sel):
                parts.append(sel)
        if not parts:
            rules[name] = None
            return
        s = pd.concat(parts)
        rules[name] = {
            "笔数": len(s),
            "超额5日%": s.exc5.mean(), "超额20日%": s.exc20.mean(),
            "超额60日%": s.exc60.mean(),
            "胜率20日%": (s.exc20 > 0).mean() * 100,
            "t值20日": tstat(s.exc20),
        }

    add_rule("R0 现状: rs>0 + 回撤3-40 + RS最高8只",
             lambda g: pick(g[(g.rs20 > 0) & g.pullback.between(3, 40)], "rs20"))
    add_rule("R1 反向: 同上但RS最低8只",
             lambda g: pick(g[(g.rs20 > 0) & g.pullback.between(3, 40)], "rs20", True))
    add_rule("R2 仅过滤不排序(前8只)",
             lambda g: pick(g[(g.rs20 > 0) & g.pullback.between(3, 40)]))
    add_rule("R3 深度回调: 回撤15-40 + 量比>1.2",
             lambda g: pick(g[(g.rs20 > 0) & g.pullback.between(15, 40) & (g.vol_ratio > 1.2)], "rs20"))
    add_rule("R4 企稳确认: 站上MA10 + 量比>1.2",
             lambda g: pick(g[(g.rs20 > 0) & g.pullback.between(3, 40)
                              & g.above_ma10 & (g.vol_ratio > 1.2)], "rs20"))
    add_rule("R5 落后补涨: rs<0 + 回撤>15 + 最弱8只",
             lambda g: pick(g[(g.rs20 < 0) & (g.pullback > 15)], "rs20", True))
    add_rule("R6 纯业绩: 增速最高8只",
             lambda g: pick(g, "profit_yoy"))
    add_rule("R7 业绩+深度回调(不看RS)",
             lambda g: pick(g[(g.pullback.between(15, 40)) & (g.gain60 < 20)], "profit_yoy"))
    add_rule("R8 只在指数>MA时: rs>0+回撤3-40+RS最高",
             lambda g: pick(g[(g.rs20 > 0) & g.pullback.between(3, 40) & g.idx_above_ma], "rs20"))
    add_rule("R9 完全不筛: 全池随机8只(基准参照)",
             lambda g: pick(g))
    add_rule("R10 只买回调>20%的高增速(均值回复)",
             lambda g: pick(g[g.pullback > 20], "profit_yoy"))
    # 基于分层发现的组合规则
    add_rule("R11 排除过热RS>30 + 回撤>20 + 按增速排序",
             lambda g: pick(g[(g.rs20 <= 30) & (g.pullback > 20)], "profit_yoy"))
    add_rule("R12 排除过热RS>30 + 近5日跌 + 回撤越深越优先",
             lambda g: pick(g[(g.rs20 <= 30) & (g.ret5 <= 0)], "pullback"))
    add_rule("R13 排除过热 + 回撤>20 + 缩量(量比<1.2) + 按增速",
             lambda g: pick(g[(g.rs20 <= 30) & (g.pullback > 20) & (g.vol_ratio < 1.2)],
                            "profit_yoy"))
    add_rule("R14 RS温和(0~20) + 回撤>15 + 按增速",
             lambda g: pick(g[g.rs20.between(0, 20) & (g.pullback > 15)], "profit_yoy"))
    add_rule("R15 深回调+缩量+60日仍为负涨幅 + 按增速",
             lambda g: pick(g[(g.pullback > 20) & (g.vol_ratio < 1.2) & (g.gain60 < 0)],
                            "profit_yoy"))
    add_rule("R16 R13 + 近5日下跌",
             lambda g: pick(g[(g.rs20 <= 30) & (g.pullback > 20) & (g.vol_ratio < 1.2)
                              & (g.ret5 <= 0)], "profit_yoy"))

    t = pd.DataFrame({k: v for k, v in rules.items() if v}).T
    t = t.sort_values("超额20日%", ascending=False).round(2)
    print(t.to_string())
    print("\n注: 前瞻收益用信号日收盘→未来收盘(等权, 未扣成本), 用于比较规则相对优劣;")
    print("    R9(全池随机)可视为当期候选池的基准, 好于R9才有选股价值。")
    t.to_csv(os.path.join(OUT_DIR, "entry_rules.csv"), encoding="utf-8-sig")


if __name__ == "__main__":
    main()
