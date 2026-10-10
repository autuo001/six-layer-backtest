# -*- coding: utf-8 -*-
"""把数据瘦身成紧凑格式(目标: 整包 <100MB)。

产物:
  data/parquet/daily_all.parquet  全部个股日线合并为一个 zstd parquet
                                  (列: code,date,open,close,volume; 价格 float32)
  data/parquet/yjbb.parquet       业绩报表只留 code/name/profit_yoy/report_period/ann_date
原 daily/*.parquet 与 cache/*.csv 保留在原地(可手动删除)。

用法: python3 slim_package.py
"""
import glob
import os
import sys
import time

import pandas as pd

PKG = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(PKG, "data", "parquet")
CACHE = os.path.join(PKG, "cache")
COLS = ["code", "date", "open", "close", "volume"]


def _slim(df, code):
    df = df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close",
                            "最高": "high", "最低": "low", "成交量": "volume",
                            "turn": "turnover"})
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float32")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("float32")
    df = df[df["close"] > 0]                      # 剔除复权污染行
    df["code"] = code
    return df[COLS]


def main():
    t0 = time.time()
    frames, seen = [], set()

    # 1) 沪深300日线(优先, 质量已校验)
    for f in sorted(glob.glob(os.path.join(DATA, "daily", "*.parquet"))):
        code = os.path.basename(f)[:-8]
        df = _slim(pd.read_parquet(f), code)
        if not df.empty:
            frames.append(df)
            seen.add(code)
    print("沪深300日线 %d 只" % len(seen), flush=True)

    # 2) 候选股缓存 CSV
    n_csv = 0
    for f in sorted(glob.glob(os.path.join(CACHE, "d_*_full.csv"))):
        code = os.path.basename(f).split("_")[1]
        if code in seen:
            continue
        df = _slim(pd.read_csv(f), code)
        if not df.empty:
            frames.append(df)
            seen.add(code)
            n_csv += 1
        if n_csv % 400 == 0 and n_csv:
            print("  已合并候选 %d 只 (用时 %.0fs)" % (n_csv, time.time() - t0), flush=True)
    print("候选股缓存 %d 只, 合计 %d 只" % (n_csv, len(seen)), flush=True)

    all_df = pd.concat(frames, ignore_index=True)
    all_df = all_df.sort_values(["code", "date"], kind="mergesort").reset_index(drop=True)
    out = os.path.join(DATA, "daily_all.parquet")
    all_df.to_parquet(out, compression="zstd", index=False)
    print("写出 %s: %d 行, %.1f MB" % (out, len(all_df), os.path.getsize(out) / 1e6))

    # 3) 业绩报表瘦身
    y = pd.read_parquet(os.path.join(DATA, "yjbb.parquet"))
    y = y.rename(columns={"股票代码": "code", "股票简称": "name",
                          "净利润-同比增长": "profit_yoy", "最新公告日期": "ann_date"})
    y = y[["code", "name", "profit_yoy", "report_period", "ann_date"]]
    y["code"] = y["code"].astype(str).str.zfill(6)
    y["profit_yoy"] = pd.to_numeric(y["profit_yoy"], errors="coerce").astype("float32")
    y["ann_date"] = pd.to_datetime(y["ann_date"], errors="coerce")
    y.to_parquet(os.path.join(DATA, "yjbb.parquet"), compression="zstd", index=False)
    print("写出 yjbb.parquet: %d 行, %.1f MB" % (len(y), os.path.getsize(os.path.join(DATA, "yjbb.parquet")) / 1e6))
    print("总用时 %.0f 秒" % (time.time() - t0))


if __name__ == "__main__":
    main()
