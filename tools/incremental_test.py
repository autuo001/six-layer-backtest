# -*- coding: utf-8 -*-
"""增量检验: 六层过滤(R12) 相对 同业绩池随机选股(R9) 到底有没有加值。

方法:
  - 以"批次"为独立单位(25~34 个批次), 每批次内比较规则选中的 8 只 与 随机 8 只
  - 随机组重复 500 次取均值, 降低抽样噪声 → 得到每批次的配对差值 d_b
  - 检验: 均值 + 自助法(bootstrap) 95% 置信区间 + 符号翻转置换检验 p 值 + t 值
  - 分别看 全样本 / IS(2018-2023) / OOS(2024-2026)

用法: python3 -u incremental_test.py
"""
import os
import sys

import numpy as np
import pandas as pd

OUT_DIR = os.environ.get(
    "SIXLAYER_OUT",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output"))
N = 8            # 每批次选股数
N_DRAW = 500     # 随机组抽样次数
N_BOOT = 10000
SEED = 20261010


def pick_r12(g):
    sel = g[(g.rs20 <= 30) & (g.ret5 <= 0)]
    return sel.sort_values("pullback", ascending=False).head(N)


def stats(d, rng):
    d = np.asarray(d, dtype=float)
    d = d[~np.isnan(d)]
    if len(d) < 3:
        return dict(n=len(d))
    mean = d.mean()
    boot = np.array([rng.choice(d, len(d), replace=True).mean() for _ in range(N_BOOT)])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    signs = rng.choice([-1.0, 1.0], size=(N_BOOT, len(d)))
    perm = (signs * d).mean(axis=1)
    p = float((np.abs(perm) >= abs(mean)).mean())
    t = mean / (d.std(ddof=1) / np.sqrt(len(d))) if d.std(ddof=1) > 0 else np.nan
    return dict(n=len(d), 均值=mean, CI下=lo, CI上=hi, p值=p, t值=t,
                为正批次=int((d > 0).sum()))


def main():
    rng = np.random.default_rng(SEED)
    df = pd.read_csv(os.path.join(OUT_DIR, "candidates.csv"))
    df = df.dropna(subset=["exc20", "exc60"])
    # signal_date 兼容两种写法: 20180917(旧) 与 2018-09-17(ISO)
    sd_raw = df["signal_date"].astype(str).str.replace("-", "")
    df["signal_date"] = pd.to_datetime(sd_raw, format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["signal_date"])
    df["year"] = df["signal_date"].dt.year

    for metric in ("exc20", "exc60", "fwd20"):
        print("\n" + "=" * 92)
        print("指标: %s   (R12=六层过滤; R9=同业绩池随机8只, %d 次抽样取均值)" % (metric, N_DRAW))
        print("=" * 92)
        rows = []
        sd_is = pd.Timestamp("2023-12-31")
        for tag, mask in (("全样本", df.index == df.index),
                          ("IS 2018-2023", df.signal_date <= sd_is),
                          ("OOS 2024-2026", df.signal_date > sd_is)):
            sub = df[mask]
            diffs, r12_means, rnd_means = [], [], []
            for sd, g in sub.groupby("signal_date"):
                r12 = pick_r12(g)
                if len(r12) == 0 or len(g) < N:
                    continue
                r12_mean = r12[metric].mean()
                draws = [g[metric].sample(N, random_state=rng.integers(1 << 31)).mean()
                         for _ in range(N_DRAW)]
                rnd_mean = float(np.mean(draws))
                diffs.append(r12_mean - rnd_mean)
                r12_means.append(r12_mean)
                rnd_means.append(rnd_mean)
            if not diffs:
                continue
            s = stats(diffs, rng)
            rows.append({"区间": tag, "批次数": s["n"],
                         "R12均值%": round(float(np.mean(r12_means)), 2),
                         "随机均值%": round(float(np.mean(rnd_means)), 2),
                         "差值%": round(s["均值"], 2),
                         "95%CI": "[%.2f, %.2f]" % (s["CI下"], s["CI上"]),
                         "p值": round(s["p值"], 3), "t值": round(s["t值"], 2),
                         "为正批次数": "%d/%d" % (s["为正批次"], s["n"])})
        out = pd.DataFrame(rows)
        print(out.to_string(index=False))
        out.to_csv(os.path.join(OUT_DIR, "incremental_%s.csv" % metric),
                   index=False, encoding="utf-8-sig")

    print("\n判读: 差值(CI)不跨0 且 p<0.05 → 六层过滤在该样本区间内提供了超额;")
    print("      若 CI 跨0 或 IS 有效/OOS 失效 → 过滤的加值不可靠, 不能作为定论。")


if __name__ == "__main__":
    main()
