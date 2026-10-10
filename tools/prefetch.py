# -*- coding: utf-8 -*-
"""并行预取 v2 回测所需的全部候选股日线, 写入 bt_cache/d_<code>_full.csv。
先跑本脚本, 再跑 six_layer_v2.py 即为纯本地回测。

用法: python3 -m prefetch
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
OUT_DIR = os.environ.get("SIXLAYER_OUT", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output"))
import six_layer_v2 as m

CACHE = m.CONFIG["cache_dir"]


def needed_codes():
    """候选口径: 业绩>=阈值 去ST。若 output/missing_codes.txt 存在则优先按该清单补
    (该清单由校验脚本导出: 业绩池中缺行情、且非北交所的代码)。"""
    todo_file = os.path.join(OUT_DIR, "missing_codes.txt")
    if os.path.exists(todo_file):
        codes = [c.strip() for c in open(todo_file) if c.strip()]
        if codes:
            print("按 output/missing_codes.txt 补数据: %d 只" % len(codes))
            return codes
    codes = []
    for year in range(m.START_YEAR, m.END_YEAR + 1):
        for period in m.CONFIG["report_periods"]:
            rep = m.get_report_data(year, period)
            if rep.empty:
                continue
            df = rep[rep["profit_yoy"] >= m.CONFIG["min_profit_growth"]]
            if m.CONFIG["exclude_st"]:
                df = df[~df["name"].astype(str).str.contains("ST|退", na=False)]
            cap = m.CONFIG["max_candidates_per_batch"]
            if cap and len(df) > cap:
                df = df.head(cap)
            codes.extend(df["code"].tolist())
    return sorted(set(codes))


def fetch_one(code):
    out = os.path.join(CACHE, f"d_{code}_full.csv")
    if os.path.exists(out):
        return code, "cached"
    df, src = m._fetch_daily_any_source(code, m.INDEX_FETCH_START, f"{m.END_YEAR}1231")
    if df is None:
        return code, "FAIL"
    df = m._normalize_daily(df)
    df = df[df["close"] > 0]
    df.to_csv(out, index=False)
    return code, src


def main():
    os.makedirs(CACHE, exist_ok=True)
    codes = needed_codes()
    todo = [c for c in codes
            if not os.path.exists(os.path.join(CACHE, f"d_{c}_full.csv"))]
    print("候选总数 %d, 待下载 %d" % (len(codes), len(todo)), flush=True)
    ok = fail = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(fetch_one, c): c for c in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            code, status = fut.result()
            if status == "FAIL":
                fail += 1
            else:
                ok += 1
            if i % 50 == 0:
                print("进度 %d/%d  ok=%d fail=%d  用时 %.0fs"
                      % (i, len(todo), ok, fail, time.time() - t0), flush=True)
    print("预取完成: ok=%d fail=%d" % (ok, fail), flush=True)


if __name__ == "__main__":
    main()
