# -*- coding: utf-8 -*-
"""
六层选股回测框架 · 单文件版
=============================
把《个人炒股作战手册》的六层选股法与交易纪律做成可检验的回测框架。
单文件自带全部逻辑, 通过子命令调用:

  python3 six_layer_backtest.py core            # 核心回测(六层+交易仿真+报告+A/B+参数网格)
  python3 six_layer_backtest.py prefetch        # 预取候选股日线(联网, 三源回退, 断点续传)
  python3 six_layer_backtest.py entry_lab       # 事件级数据: 候选特征 + 建仓后5/20/60日超额
  python3 six_layer_backtest.py forward_edge    # 分层检验 + 入场规则对比 ← 改规则前先跑
  python3 six_layer_backtest.py exit_lab        # 卖出参数 × 大盘层 交叉测试
  python3 six_layer_backtest.py loss_analysis   # 亏损归因
  python3 six_layer_backtest.py freq_sweep      # 交易频率对照

数据位置(按优先级):
  1) 环境变量 SIXLAYER_DATA / SIXLAYER_CACHE / SIXLAYER_OUT
  2) 本文件同目录下的 data/parquet、cache、output
设 OFFLINE=1 表示不联网(缺数据的股票直接跳过)。

目录约定:
  data/parquet/daily/*.parquet   沪深300 成分股前复权日线
  data/parquet/yjbb.parquet      季度业绩报表
  data/parquet/index.parquet     沪深300 指数日线
  cache/                         候选股全历史日线缓存(prefetch 生成)
  output/                        报告与结果 CSV

核心结论(2018-2026, 含成本): 大盘层开 +12.1%/回撤-27.2%, 大盘层关 +23.6%/回撤-30.2%,
沪深300 同期 +6.6%/回撤-45.6%。参数依据见 core 子命令中的注释与 README。
已知乐观偏差: 业绩快照未来函数、幸存者偏差(退市股无数据)、参数敏感性大。

依赖: pip install akshare pandas numpy pyarrow
仅供个人研究, 不构成投资建议。
"""

# -*- coding: utf-8 -*-
"""
六层选股回测 · 修正版 v2
========================
对照 v1 回测框架的六个硬伤逐项修复：

  修复1  新增第①层【大盘环境】：沪深300 收盘 < 250 日线 → 整个批次空仓（原框架最大缺口）
  修复2  第③层【相对强度】真正落地：候选按近20日"个股-指数"超额收益排序，取前 N，
         不再按报表默认顺序闭眼抓（原 get_industry_rs 是死代码，已删除）
  修复3  成交写实：信号次日开盘价成交 + 滑点；止损/止盈/时间退出统一按此执行
         （原框架止损按当日收盘价成交，系统性偏乐观）
  修复4  成本入账：佣金万2.5（最低5元）+ 卖出印花税0.05% + 双边滑点千1
  修复5  涨跌停约束：一字涨停买不进、跌停卖不出（卖单顺延到能成交为止）
  修复6  建仓日加披露滞后 entry_lag_days，缓解"9月1日就用上全期中报"的未来函数
  修复7  修 bug：同一只票未清仓时再次入选会覆盖旧仓位；仓位按总权益（现金+市值）计算
  修复8  报告升级：沪深300 同期收益与最大回撤对比、分年度收益、资金占用率、
         修复1 的 A/B 对照（开/关大盘层各跑一次）、SWEEP 参数网格（检验是否过拟合）

如实告知——以下乐观偏差仍然存在，看结果时自行打折：
  - akshare 业绩报表是"报告期末全量快照"，披露滞后只能缓解、无法根除；
  - 退市股的历史行情多数查不到，幸存者偏差仍在 → 真实结果应比回测更差；
  - 本回测只回答"这套规则的粗糙近似有没有方向性优势"，不承诺任何真实收益。

v3 改动（全部基于事件级数据检验, 不是拍脑袋）：
  工具: entry_lab.py(事件特征+前瞻超额) / forward_edge.py(分层检验+规则对比)
        / exit_lab.py(卖出参数×大盘层交叉) / loss_analysis.py(亏损归因)
  ① 第③层由"买相对强度最高"改为"排除过热(RS>30%不买)"——分层显示RS>40%档
     20日超额-1.47%, 追强是反向指标; 候选池随机选股超额+1.12%, 排序把它做没了。
  ② 第②层由"回撤3-40%"改为"深回调20-45%"——回撤>30%档超额+1.60%(t=3.9)。
  ③ 新增"近5日不涨"过滤——<-5%档超额+1.51%(t=5.0), 均值回复优于追涨。
  ④ 卖出纪律放宽: 止损-4%→-15%, 止盈9/18→12/25, 持有60→90日。原参数在75%的
     持仓上触发止损(平均最大浮亏-6.09%), 且"止损越宽越好"在交叉测试中单调成立。
  ⑤ 大盘层默认关闭(保留A/B): 候选池在"指数<MA"时20日超额+1.47%, 在">MA"时-0.29%,
     均值回复型入场天然偏好弱市, 加过滤反而削掉最好的批次。
  结果: 总收益 -15.7% → +12.1%(大盘层开) / +23.6%(大盘层关)。
  诚实声明: 放宽/取消止损会让幸存者偏差的影响最大化(退市股在样本外), 无止损变体
  虽然回测更高(+38%~+165%), 但那是上限而非预期。

依赖：pip install akshare pandas numpy
运行：python3 六层选股回测_修正版.py        （完整回测 + A/B 对照 + 参数网格）
"""

import os
import socket
import time

socket.setdefaulttimeout(60)  # C层(SSL握手)硬超时: 防远程黑洞连接永久卡死

import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ============ 0. 本地数据层(替代逐窗口联网) ============
# 包内相对路径, 可用环境变量覆盖: SIXLAYER_DATA / SIXLAYER_CACHE / SIXLAYER_OUT
PKG_ROOT = os.path.dirname(os.path.abspath(__file__))   # 单文件所在目录
V1_DATA = os.environ.get("SIXLAYER_DATA", os.path.join(PKG_ROOT, "data", "parquet"))
OUT_DIR = os.environ.get("SIXLAYER_OUT", os.path.join(PKG_ROOT, "output"))
os.makedirs(OUT_DIR, exist_ok=True)
_DAILY_FULL = {}   # code -> 全历史日线 DataFrame
_DAILY_TRIED = set()


def _retry(fn, times=3, sleep=3, timeout=45):
    import signal
    import threading

    # 子线程里 SIGALRM 不可用: 靠 socket.setdefaulttimeout 兜底, 直接调用
    if threading.current_thread() is not threading.main_thread():
        last = None
        for i in range(times):
            try:
                return fn()
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(sleep * (i + 1))
        raise last

    def _h(signum, frame):
        raise TimeoutError("timeout %ds" % timeout)

    last = None
    for i in range(times):
        old = signal.signal(signal.SIGALRM, _h)
        signal.alarm(timeout)
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(sleep * (i + 1))
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
    raise last


def _fetch_daily_any_source(code, start, end):
    """腾讯 -> 东财 -> 新浪, 任一成功即返回(列统一)。"""
    errs = []
    for name, fn in (
        ("tx", lambda: ak.stock_zh_a_hist_tx(
            symbol=("sh" if code.startswith("6") else "sz") + code,
            start_date=start, end_date=end, adjust="qfq")),
        ("em", lambda: ak.stock_zh_a_hist(symbol=code, period="daily",
                                          start_date=start, end_date=end, adjust="qfq")),
        ("sina", lambda: ak.stock_zh_a_daily(
            symbol=("sh" if code.startswith("6") else "sz") + code,
            start_date=start, end_date=end, adjust="qfq")),
    ):
        try:
            df = _retry(fn, times=2, sleep=3, timeout=45)
            if df is not None and not df.empty:
                return df, name
        except Exception as e:  # noqa: BLE001
            errs.append("%s:%s" % (name, str(e)[:40]))
        time.sleep(1.5)
    print("    !! %s 三源均失败 %s" % (code, errs))
    return None, None


def _normalize_daily(df):
    df = df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close",
                            "最高": "high", "最低": "low", "成交量": "volume"})
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "open", "close", "high", "low", "volume"]].sort_values("date").reset_index(drop=True)


_DAILY_ALL = None      # (DataFrame, {code: (起, 止)}) —— 瘦身包的单文件日线


def _load_daily_all():
    """读取 data/parquet/daily_all.parquet(全部个股日线合并文件), 返回(code切片索引)。"""
    global _DAILY_ALL
    if _DAILY_ALL is not None:
        return _DAILY_ALL
    path = os.path.join(V1_DATA, "daily_all.parquet")
    if not os.path.exists(path):
        _DAILY_ALL = (pd.DataFrame(), {})
        return _DAILY_ALL
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["code", "date"], kind="mergesort").reset_index(drop=True)
    bounds = {c: (int(g.index[0]), int(g.index[-1]) + 1)
              for c, g in df.groupby("code", sort=False)}
    _DAILY_ALL = (df, bounds)
    return _DAILY_ALL


def load_full_daily(code):
    """code -> 2016 至今全历史日线(内存缓存); 单文件合并库优先, 其余本地缓存次之。"""
    if code in _DAILY_FULL:
        return _DAILY_FULL[code]
    if code in _DAILY_TRIED:
        return _DAILY_FULL.get(code, pd.DataFrame())
    _DAILY_TRIED.add(code)

    all_df, bounds = _load_daily_all()
    if code in bounds:
        i0, i1 = bounds[code]
        df = all_df.iloc[i0:i1].reset_index(drop=True)
        _DAILY_FULL[code] = df
        return df

    path = os.path.join(V1_DATA, "daily", code + ".parquet")
    cache_csv = os.path.join(CONFIG["cache_dir"], f"d_{code}_full.csv")
    if os.path.exists(path):
        df = pd.read_parquet(path)
        df = df.rename(columns={"turn": "turnover"})
        df["date"] = pd.to_datetime(df["date"])
        df = df[df["close"] > 0]                      # 剔除复权污染的占位行
        _DAILY_FULL[code] = df.reset_index(drop=True)
        return _DAILY_FULL[code]
    if os.path.exists(cache_csv):
        df = pd.read_csv(cache_csv, parse_dates=["date"])
        df = df[df["close"] > 0]
        _DAILY_FULL[code] = df.reset_index(drop=True)
        return _DAILY_FULL[code]
    if os.environ.get("OFFLINE"):           # 离线模式: 无缓存即跳过, 不联网
        _DAILY_FULL[code] = pd.DataFrame()
        return _DAILY_FULL[code]
    df, src = _fetch_daily_any_source(code, INDEX_FETCH_START, f"{END_YEAR}1231")
    if df is not None:
        df = _normalize_daily(df)
        df.to_csv(os.path.join(CONFIG["cache_dir"], f"d_{code}_full.csv"), index=False)
        _DAILY_FULL[code] = df
    else:
        _DAILY_FULL[code] = pd.DataFrame()
    return _DAILY_FULL[code]


_YJBB_LOCAL = None


def load_yjbb_local():
    """从 v1 缓存的全量业绩报表(44期)构建 {(year, period): DataFrame}。"""
    global _YJBB_LOCAL
    if _YJBB_LOCAL is not None:
        return _YJBB_LOCAL
    df = pd.read_parquet(os.path.join(V1_DATA, "yjbb.parquet"))
    df = df.rename(columns={"股票代码": "code", "净利润-同比增长": "profit_yoy",
                            "股票简称": "name", "最新公告日期": "ann_date"})
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["profit_yoy"] = pd.to_numeric(df["profit_yoy"], errors="coerce")
    out = {}
    for period, g in df.groupby("report_period"):
        y = str(period)[:4]
        md = str(period)[4:]
        keep = ["code", "name", "profit_yoy"]
        if "ann_date" in g.columns:
            g = g.copy()
            g["ann_date"] = pd.to_datetime(g["ann_date"], errors="coerce")
            keep.append("ann_date")
        out[(y, md)] = g[keep].reset_index(drop=True)
    _YJBB_LOCAL = out
    return out


# ============ 1. 参数区 ============
CONFIG = {
    # ① 业绩层：归母净利同比增速下限（%）。注意：阈值是待检验参数，别当真理（见 SWEEP）
    "min_profit_growth": 50,
    "report_periods": ["0331", "0630", "0930", "1231"],   # 一季报/中报/三季报/年报 全用上
    # 披露日对齐: True=只用信号日之前实际已公告的报表, False=原快照口径(推荐)
    # 注意: yjbb 的"最新公告日期"多为更正/重述日, 用它严格过滤会把候选砍掉90%以上, 故默认关
    "strict_disclosure": False,
    "force_exit_no_bar_days": 90,   # 连续无行情(停牌/退市)超过N个自然日 → 按最后收盘价强制平仓
    "delist_haircut": 0.0,          # 该强制平仓的额外惩罚比例(0=按最后价, 0.5=再打五折)
    "delist_prob": 0.0,             # 压力测试: 每笔建仓被判"退市归零"的概率
    "delist_loss": 0.5,             # 压力测试: 被判退市时的损失比例(0.5=亏50%)
    "stress_seed": 20261010,        # 压力测试随机种子(保证可复现)

    # ② 位置层：现价距 60 日最高收盘价的回撤区间（%）
    # 分层检验: 回撤>30%档 20日超额+1.60%(t=3.9), 回撤<5%档≈0 → 改为偏深回调(均值回复)
    "pullback_min": 20,
    "pullback_max": 45,

    # ③ 相对强度（分层检验结论: 追强是反向指标, >40%档超额-1.47%）
    "rs_lookback": 20,
    "rs_max": 30,                 # 排除过热: 近20日相对指数超额 >30% 不买
    "rs_min": -1000,              # 允许落后股(<-10%档超额+0.90%, t=3.4)
    "ret5_max": 0,                # 建仓前5日需为下跌/走平(None=关闭); <-5%档超额+1.51%(t=5.0)
    "rank_by": "pullback",        # 入选排序: pullback(跌得越深越优先) / profit_yoy / rs

    # ④ 排雷
    "exclude_st": True,
    "max_60d_gain": 100,          # 60 日内涨幅 >100% 视为高位，永不接盘
    "min_list_days": 180,         # 排除次新股

    # ①' 大盘环境层：指数收盘 < MA120 → 本批次空仓
    # 分层证据: 候选池在"指数<MA"时的20日超额(+1.47%)显著好于"指数>MA"(-0.29%),
    # 均值回复型入场本身偏好弱市 → 默认关闭, 但保留 A/B 对照以观察其绝对回撤保护作用
    "use_regime_filter": False,
    "regime_index_code": "000300",   # 沪深300
    "regime_ma": 120,                # MA250 过于迟钝, 放宽到 MA120 以增加可交易批次

    # ⑤ 交易执行（写实化）
    # 参数依据: 亏损归因显示"均值回复买点 + 动量紧止损"性格冲突, -4%止损在75%的持仓上触发,
    # 且反事实测试中"止损越宽越好"是单调的 → 默认放宽到 -15%, 持有 90 交易日, 止盈 12/25
    "entry_lag_days": 10,         # 披露截止后 N 个交易日才出信号（缓解未来函数）
    "stop_loss_pct": 0.15,        # 收盘较成本 <= -15% → 次日开盘卖
    "take_profit_1": 0.12,        # +12% 卖一半（次日开盘）
    "take_profit_2": 0.25,        # +25% 清仓（次日开盘）
    "max_hold_days": 90,          # 最长持有 90 个交易日（均值回复需要时间兑现）
    "max_positions": 8,           # 持仓只数(高频口径: 8 只, 分散度换胜率)
    "position_pct": 0.125,        # 单票占总权益比例
    "initial_capital": 100000,

    # ⑥ 成本
    "commission": 0.00025,        # 佣金万2.5
    "min_commission": 5.0,        # 最低5元
    "stamp_tax": 0.0005,          # 卖出印花税 0.05%
    "slippage": 0.001,            # 滑点 千1（单边）

    # ⑦ 涨跌停（主板 ±10%；回测池以主板为主，简化处理，创业板/科创板的 20% 未区分）
    "limit_pct": 0.10,

    # ⑧ 运行控制
    "max_candidates_per_batch": 0,     # 0=不限制(行情已本地缓存, 全量细算无额外成本)
    "cache_dir": os.environ.get("SIXLAYER_CACHE",
                                os.path.join(PKG_ROOT, "cache")),  # 候选股日线磁盘缓存
}

START_YEAR, END_YEAR = 2018, 2026      # 覆盖 2018 熊 / 2019-21 / 2022 熊 / 2024-26
INDEX_FETCH_START = "20160101"         # 指数多取一年，保证 250 日线在 2018 年初已有效

# ============ 2. 数据获取（带磁盘缓存） ============

os.makedirs(CONFIG["cache_dir"], exist_ok=True)


def _cached_csv(name: str, fetcher) -> pd.DataFrame:
    path = os.path.join(CONFIG["cache_dir"], name)
    if os.path.exists(path):
        return pd.read_csv(path, parse_dates=["date"] if "date" in pd.read_csv(path, nrows=0).columns else None)
    df = fetcher()
    if df is not None and not df.empty:
        df.to_csv(path, index=False)
    return df if df is not None else pd.DataFrame()


def get_trade_cal() -> list:
    """以 v1 缓存的沪深300指数交易日为准(避免联网)。"""
    df = pd.read_parquet(os.path.join(V1_DATA, "index.parquet"))
    return sorted(pd.to_datetime(df["date"]).dt.strftime("%Y%m%d").tolist())


def get_index_daily() -> pd.DataFrame:
    """沪深300 日线(本地缓存优先), 含 MA250。"""
    path = os.path.join(CONFIG["cache_dir"], "index_000300.csv")
    if os.path.exists(path):
        df = pd.read_csv(path, parse_dates=["date"])
    else:
        df = pd.read_parquet(os.path.join(V1_DATA, "index.parquet"))
        df["date"] = pd.to_datetime(df["date"])
        df = df[["date", "open", "close"]].sort_values("date").reset_index(drop=True)
        df.to_csv(path, index=False)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["ma"] = df["close"].rolling(CONFIG["regime_ma"]).mean()
    return df


def get_report_data(year: int, period: str, as_of: str = None) -> pd.DataFrame:
    """业绩报表: 优先 v1 本地全量缓存, 缺失期再联网补。

    as_of(YYYYMMDD) 且 strict_disclosure=True 时, 只保留公告日 <= as_of 的行,
    避免"报表期末全量快照"引入的未来函数。
    """
    if as_of and CONFIG.get("strict_disclosure", True):
        # 需要公告日 → 走本地缓存的完整字段
        local = load_yjbb_local()
        if (str(year), period) in local:
            g = local[(str(year), period)]
            if "ann_date" in g.columns:
                g = g[g["ann_date"] <= pd.to_datetime(as_of)]
            return g[["code", "name", "profit_yoy"]].reset_index(drop=True)
    local = load_yjbb_local()
    if (str(year), period) in local:
        return local[(str(year), period)][["code", "name", "profit_yoy"]]
    def fetch():
        df = ak.stock_yjbb_em(date=f"{year}{period}")
        df = df.rename(columns={"股票代码": "code", "净利润-同比增长": "profit_yoy",
                                "净利润-净利润": "profit", "股票简称": "name"})
        df["code"] = df["code"].astype(str).str.zfill(6)
        df["profit_yoy"] = pd.to_numeric(df["profit_yoy"], errors="coerce")
        return df[["code", "name", "profit_yoy"]]
    df = _cached_csv(f"yjbb_{year}{period}.csv", lambda: _retry(fetch, times=3, sleep=4, timeout=45))
    if not df.empty:
        df["code"] = df["code"].astype(str).str.zfill(6)
        df["profit_yoy"] = pd.to_numeric(df["profit_yoy"], errors="coerce")
    return df


_DAILY_MEMO = {}   # (code, signal_date) -> DataFrame，避免 SWEEP 重复拉取


def get_daily(code: str, start: str, end: str) -> pd.DataFrame:
    """从全历史缓存切片 [start, end], 不再逐窗口联网。"""
    key = (code, start, end)
    if key in _DAILY_MEMO:
        return _DAILY_MEMO[key]
    full = load_full_daily(code)
    if full.empty:
        _DAILY_MEMO[key] = full
        return full
    d = full[(full["date"] >= pd.to_datetime(start)) & (full["date"] <= pd.to_datetime(end))]
    _DAILY_MEMO[key] = d
    return d


# ============ 3. 六层筛选 ============

def batch_signal_date(cal: list, year: int, period: str) -> str:
    """披露截止后第 entry_lag_days 个交易日为信号日。

    年报(1231)的法定披露截止是次年 4/30, 故 cutoff 落在 year+1。
    """
    cutoffs = {"0331": f"{year}0430",      # 一季报
               "0630": f"{year}0831",      # 中报
               "0930": f"{year}1031",      # 三季报
               "1231": f"{year + 1}0430"}  # 年报
    cutoff = cutoffs.get(period, f"{year}1031")
    after = [d for d in cal if d > cutoff]
    if not after:
        return None
    idx = min(CONFIG["entry_lag_days"], len(after) - 1)
    return after[idx]


def screen_batch(year: int, period: str, signal_date: str,
                 index_df: pd.DataFrame) -> dict:
    """返回 {signal_date, regime_ok, picks:[{code,rs,pullback}...]}"""
    rep = get_report_data(year, period, as_of=signal_date)
    out = {"signal_date": signal_date, "regime_ok": True, "picks": []}
    if rep.empty:
        print(f"  [{year}{period}] 业绩报表获取失败，跳过")
        return out

    # 第①'层 大盘环境
    idx_row = index_df[index_df["date"] == pd.to_datetime(signal_date)]
    if idx_row.empty:
        idx_row = index_df[index_df["date"] <= pd.to_datetime(signal_date)].tail(1)
    if not idx_row.empty and CONFIG["use_regime_filter"]:
        if float(idx_row.iloc[-1]["close"]) < float(idx_row.iloc[-1]["ma"]):
            out["regime_ok"] = False
            return out

    # 第①层 业绩 + 第④层 排雷（ST）
    df = rep[rep["profit_yoy"] >= CONFIG["min_profit_growth"]].copy()
    if CONFIG["exclude_st"]:
        df = df[~df["name"].astype(str).str.contains("ST|退", na=False)]
    n0 = len(df)
    cap = CONFIG["max_candidates_per_batch"]
    if cap and len(df) > cap:
        # 前置排序: 按业绩增速降序截断(原写法按报表默认顺序 head, 截断近乎随机)
        df = df.sort_values("profit_yoy", ascending=False).head(cap)
        print(f"  [{year}{period}] 业绩层通过 {n0} 只，超过上限 {cap}，"
              f"按增速降序取前 {cap} 只（仍有截断偏差）")
    print(f"  [{year}{period}] 业绩层通过 {n0} 只，进入细算")

    # 第②③④层：拉日线统一算（回撤、60日涨幅、相对强度、上市天数）
    start = (datetime.strptime(signal_date, "%Y%m%d") - timedelta(days=200)).strftime("%Y%m%d")
    idx_close = index_df.set_index("date")["close"]
    lb = CONFIG["rs_lookback"]
    sig_dt = pd.to_datetime(signal_date)

    rows = []
    for _, r in df.iterrows():
        code = r["code"]
        # 修复: 用"上市至今"的历史判断次新(原写法用200天窗口长度, 恒<180 → 恒无入选)
        d = get_daily(code, INDEX_FETCH_START, signal_date)
        if d.empty or len(d) < max(CONFIG["min_list_days"], lb + 5):
            continue                                   # 次新股或数据缺失（含已退市，幸存者偏差来源）
        d = d.sort_values("date")
        last = d.iloc[-1]
        high60 = d["close"].tail(60).max()
        pullback = (high60 - last["close"]) / high60 * 100
        gain60 = (last["close"] / d["close"].iloc[-60] - 1) * 100
        if gain60 > CONFIG["max_60d_gain"]:
            continue                                   # 短期翻倍，永不接盘
        if not (CONFIG["pullback_min"] <= pullback <= CONFIG["pullback_max"]):
            continue                                   # 位置不符
        hist = idx_close[idx_close.index <= sig_dt]
        if len(hist) < lb + 1:
            continue
        r_idx = hist.iloc[-1] / hist.iloc[-1 - lb] - 1
        r_stk = last["close"] / d["close"].iloc[-1 - lb] - 1
        rs = (r_stk - r_idx) * 100
        # 第③层改为"排除过热"而非"买最强"(分层检验: 追强是反向指标)
        if rs > CONFIG["rs_max"] or rs < CONFIG["rs_min"]:
            continue
        ret5 = (last["close"] / d["close"].iloc[-6] - 1) * 100
        if CONFIG["ret5_max"] is not None and ret5 > CONFIG["ret5_max"]:
            continue                                   # 要求近期下跌/走平(均值回复)
        rows.append({"code": code, "rs": rs / 100.0, "rs_pct": round(rs, 1),
                     "pullback": round(pullback, 1), "ret5": round(ret5, 1),
                     "profit_yoy": float(r["profit_yoy"]),
                     "close": float(last["close"])})

    key = CONFIG["rank_by"]
    rows.sort(key=lambda x: x[key], reverse=(key != "rs"))   # 默认降序; rs 温和者优先则升序
    if key == "rs":
        rows.sort(key=lambda x: abs(x["rs"]))
    out["picks"] = rows[:CONFIG["max_positions"]]
    return out


# ============ 4. 交易与组合 ============

class Pos:
    def __init__(self, code, shares, entry, doomed=False):
        self.code, self.shares, self.entry = code, shares, entry
        self.days = 0
        self.half_sold = False
        self.last_close = entry
        self.doomed = doomed        # 压力测试: 该笔被判"退市"(按 delist_loss 计亏)


def _buy_gross(px, sh):
    return px * sh + max(px * sh * CONFIG["commission"], CONFIG["min_commission"])


def _sell_net(px, sh):
    g = px * sh
    return g - max(g * CONFIG["commission"], CONFIG["min_commission"]) - g * CONFIG["stamp_tax"]


def simulate(batches: list, cal: list, liquidate_at_end: bool = False) -> dict:
    """逐日仿真：T 收盘出信号 → T+1 开盘成交；含涨跌停限制与全部成本。

    liquidate_at_end=True 时, 窗口结束仍持仓的按最后收盘价卖出(含成本),
    保证区间收益完全实现 —— 用于 OOS 分段验证。
    """
    import random as _random
    cash = CONFIG["initial_capital"]
    positions: dict[str, Pos] = {}
    pending_buys: list[dict] = []      # 次日开盘买
    pending_sells: list[dict] = []     # 次日开盘卖（跌停则顺延）
    trades, equity_curve, last_close = [], [], {}
    rng = _random.Random(CONFIG["stress_seed"])
    n_doomed = 0

    sig_map = {b["signal_date"]: b for b in batches}
    limit = CONFIG["limit_pct"]

    for d in cal:
        dt = pd.to_datetime(d)
        # ---- 开盘：先处理挂单 ----
        for o in list(pending_sells):
            code = o["code"]
            if code not in positions:
                pending_sells.remove(o); continue
            hd = get_daily(code, (dt - timedelta(days=30)).strftime("%Y%m%d"), d)
            row = hd[hd["date"] == dt]
            if row.empty:
                continue                                   # 停牌，顺延
            op = float(row.iloc[0]["open"])
            prev = last_close.get(code, positions[code].entry)
            if op <= prev * (1 - limit + 0.004):           # 开盘跌停，卖不出，顺延
                continue
            px = op * (1 - CONFIG["slippage"])
            pos = positions[code]
            if pos.doomed:                                 # 压力测试: 退市归零档
                px = min(px, pos.entry * (1 - CONFIG["delist_loss"]))
            sh = min(o["shares"], pos.shares)
            cash += _sell_net(px, sh)
            trades.append((d, code, o["reason"], px, sh))
            pos.shares -= sh
            if pos.shares == 0:
                del positions[code]
            pending_sells.remove(o)

        for o in list(pending_buys):
            code = o["code"]
            if code in positions:                          # 修复：同票未清仓不加仓
                pending_buys.remove(o); continue
            hd = get_daily(code, (dt - timedelta(days=30)).strftime("%Y%m%d"), d)
            row = hd[hd["date"] == dt]
            if row.empty:
                pending_buys.remove(o); continue           # 停牌，放弃本笔
            op = float(row.iloc[0]["open"])
            prev = last_close.get(code, o["signal_close"])
            if op >= prev * (1 + limit - 0.004):           # 开盘涨停，买不进，放弃
                pending_buys.remove(o); continue
            px = op * (1 + CONFIG["slippage"])
            equity = cash + sum(p.shares * last_close.get(c, p.entry) for c, p in positions.items())
            budget = equity * CONFIG["position_pct"]
            sh = int(budget / (px * 100)) * 100
            if sh <= 0 or _buy_gross(px, sh) > cash:
                pending_buys.remove(o); continue
            cash -= _buy_gross(px, sh)
            doomed = CONFIG["delist_prob"] > 0 and rng.random() < CONFIG["delist_prob"]
            if doomed:
                n_doomed += 1
            positions[code] = Pos(code, sh, px, doomed=doomed)
            trades.append((d, code, "buy", px, sh))
            pending_buys.remove(o)

        # ---- 收盘：出信号 ----
        if d in sig_map:
            b = sig_map[d]
            if b["regime_ok"]:
                for p in b["picks"]:
                    if p["code"] not in positions and len(positions) + len(pending_buys) < CONFIG["max_positions"]:
                        pending_buys.append({"code": p["code"], "signal_close": p.get("close", np.nan)})

        for code in list(positions):
            pos = positions[code]
            hd = get_daily(code, (dt - timedelta(days=30)).strftime("%Y%m%d"), d)
            row = hd[hd["date"] == dt]
            if row.empty:
                # 长期无行情(停牌/退市): 超过阈值按最后收盘价强制平仓, 避免仓位永久挂死
                full = load_full_daily(code)
                last_dt = full["date"].max() if not full.empty else None
                if last_dt is not None and (dt - last_dt).days > CONFIG["force_exit_no_bar_days"]:
                    px = float(last_close.get(code, pos.entry)) * (1 - CONFIG["delist_haircut"])
                    cash += _sell_net(px, pos.shares)
                    trades.append((d, code, "delist_exit", px, pos.shares))
                    last_close[code] = px
                    del positions[code]
                continue                                   # 停牌日：不计持有天数
            close = float(row.iloc[0]["close"])
            last_close[code] = close
            pos.days += 1
            r = close / pos.entry - 1
            already = any(o["code"] == code for o in pending_sells)
            if not already:
                if r <= -CONFIG["stop_loss_pct"]:
                    pending_sells.append({"code": code, "shares": pos.shares, "reason": "stop_loss"})
                elif (not pos.half_sold) and r >= CONFIG["take_profit_1"]:
                    half = (pos.shares // 200) * 100        # 整手卖一半(原写法 //2 会产生50股碎单)
                    pos.half_sold = True
                    if half > 0:
                        pending_sells.append({"code": code, "shares": half, "reason": "take_profit_1"})
                elif r >= CONFIG["take_profit_2"]:
                    pending_sells.append({"code": code, "shares": pos.shares, "reason": "take_profit_2"})
                elif pos.days >= CONFIG["max_hold_days"]:
                    pending_sells.append({"code": code, "shares": pos.shares, "reason": "time_exit"})

        mv = sum(p.shares * last_close.get(c, p.entry) for c, p in positions.items())
        equity_curve.append((d, cash + mv))

    # 窗口末清算(可选): 把未平仓的按最后收盘价卖出, 保证区间收益完全实现
    if liquidate_at_end and positions:
        last_d = cal[-1]
        for code, pos in list(positions.items()):
            px = float(last_close.get(code, pos.entry))
            if pos.doomed:
                px = min(px, pos.entry * (1 - CONFIG["delist_loss"]))
            cash += _sell_net(px, pos.shares)
            trades.append((last_d, code, "window_end", px, pos.shares))
            del positions[code]
        equity_curve[-1] = (last_d, cash)

    return {"trades": trades, "equity": equity_curve, "n_doomed": n_doomed}


# ============ 5. 报告 ============

def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    return ((equity - peak) / peak).min()


def yearly_returns(dates: list, values: list) -> pd.Series:
    s = pd.Series(values, index=pd.to_datetime(dates)).sort_index()
    return s.resample("YE").last().pct_change()   # 首年用期初资金处理在外层


def report(result: dict, index_df: pd.DataFrame, batches: list, label: str):
    trades = pd.DataFrame(result["trades"], columns=["date", "code", "action", "price", "shares"])
    eq = pd.DataFrame(result["equity"], columns=["date", "equity"])
    eq["date"] = pd.to_datetime(eq["date"])
    total_ret = eq["equity"].iloc[-1] / CONFIG["initial_capital"] - 1
    mdd = max_drawdown(eq["equity"])
    n_sell = len(trades[trades["action"] != "buy"])
    exposure = (eq["equity"] != CONFIG["initial_capital"]).mean()   # 粗略资金占用率

    idx = index_df.set_index("date")["close"]
    idx = idx[(idx.index >= eq["date"].iloc[0]) & (idx.index <= eq["date"].iloc[-1])]
    bench_ret = idx.iloc[-1] / idx.iloc[0] - 1
    bench_mdd = max_drawdown(idx)

    skipped = [b["signal_date"] for b in batches if not b["regime_ok"]]

    print("\n" + "=" * 52)
    print(f"回测结果（{label}）")
    print("=" * 52)
    print(f"总收益率        : {total_ret * 100:+.1f}%   （沪深300 同期 {bench_ret * 100:+.1f}%）")
    print(f"最大回撤        : {mdd * 100:.1f}%   （沪深300 同期 {bench_mdd * 100:.1f}%）")
    sells = trades[trades["action"] != "buy"]
    print(f"卖出笔数        : {n_sell}")
    print(f"止损占比        : {(sells['action'] == 'stop_loss').mean() * 100:.0f}%  (占卖出笔数)")
    print(f"资金占用率(日)  : {exposure * 100:.0f}%")
    print(f"空仓批次(大盘层): {len(skipped)} 次  {skipped}")
    if n_sell:
        # 逐笔配对盈亏: 同时给"等权(按腿)"和"按金额加权"两个口径
        buys = trades[trades["action"] == "buy"]
        pnl, dollars, costs = [], [], []
        for _, s in trades[trades["action"] != "buy"].iterrows():
            b = buys[(buys["code"] == s["code"]) & (buys["date"] <= s["date"])]
            if b.empty:
                continue
            bp = float(b.iloc[-1]["price"])
            sp = float(s["price"])
            sh = float(s["shares"])
            pnl.append(sp / bp - 1)
            dollars.append((sp - bp) * sh)      # 该腿盈亏金额(不含费用)
            costs.append(bp * sh)               # 该腿买入成本
        pnl = pd.Series(pnl)
        dollars, costs = np.array(dollars), np.array(costs)
        w = dollars.sum() / costs.sum() if costs.sum() else float("nan")
        print(f"胜率            : {(pnl > 0).mean() * 100:.0f}% (按腿等权)   "
              f"盈亏比 {abs(pnl[pnl > 0].mean() / pnl[pnl <= 0].mean()):.2f}   "
              f"单笔期望 {pnl.mean() * 100:+.2f}% (等权)")
        print(f"金额加权期望    : {w * 100:+.2f}%   "
              f"(核对: 腿盈亏合计 {dollars.sum():+.0f} 元 / 成本 {costs.sum():.0f} 元)")
        print("注: 等权口径把『止盈一半』的半仓赢家与全仓输家同等看待, 会系统性偏乐观, 以金额加权为准")
    print("\n分年度（策略 vs 沪深300）：")
    eq_y = eq.set_index("date")["equity"].resample("YE").last()
    eq_y.iloc[0] = CONFIG["initial_capital"]
    strat_y = eq_y.pct_change()
    strat_y.iloc[0] = eq_y.iloc[0] / CONFIG["initial_capital"] - 1
    bench_y = idx.resample("YE").last().pct_change()
    tbl = pd.DataFrame({"策略%": (strat_y * 100).round(1), "沪深300%": (bench_y * 100).round(1)})
    print(tbl.dropna(how="all").to_string())
    return {"total_ret": total_ret, "mdd": mdd, "bench_ret": bench_ret, "bench_mdd": bench_mdd,
            "skipped": len(skipped)}


# ============ 6. 主流程 ============

def build_batches(cal: list, index_df: pd.DataFrame, verbose: bool = True) -> list:
    batches = []
    for year in range(START_YEAR, END_YEAR + 1):
        for period in CONFIG["report_periods"]:
            sd = batch_signal_date(cal, year, period)
            if not sd:
                continue
            if verbose:
                print(f"\n=== {year} {period} 期，信号日 {sd} ===")
            b = screen_batch(year, period, sd, index_df)
            if verbose:
                if not b["regime_ok"]:
                    print(f"  大盘环境层：指数 < MA{CONFIG['regime_ma']} → 本批次【空仓】")
                else:
                    pick_str = [(p["code"], f"RS{p['rs'] * 100:.0f}%") for p in b["picks"]]
                    print(f"  入选: {pick_str}")
            batches.append((year, period, b))
    # 合并信号日相同的批次(一季报与年报的披露截止同为4/30 → 信号日撞车),
    # 否则 simulate 的 {signal_date: batch} 会用后者覆盖前者, 静默丢掉一半信号
    merged = {}
    for year, period, b in batches:
        key = b["signal_date"]
        if key not in merged:
            merged[key] = b
            merged[key]["sources"] = ["%s%s" % (year, period)]
            continue
        m0 = merged[key]
        m0["sources"].append("%s%s" % (year, period))
        if b["regime_ok"]:
            m0["regime_ok"] = True
        have = {p["code"] for p in m0["picks"]}
        for p in b["picks"]:
            if p["code"] not in have:
                m0["picks"].append(p)
        m0["picks"].sort(key=lambda x: x["rs"], reverse=True)
    return list(merged.values())


def run_core():
    print("拉取指数与交易日历……")
    index_df = get_index_daily()
    cal_all = get_trade_cal()
    cal = [d for d in cal_all if f"{START_YEAR}0101" <= d <= f"{END_YEAR}1231"]

    # A/B 对照：同样信号，只切换大盘环境层
    print("\n########## A 组：开启大盘环境层 ##########")
    CONFIG["use_regime_filter"] = True
    batches_a = build_batches(cal, index_df)
    res_a = simulate(batches_a, cal)
    rep_a = report(res_a, index_df, batches_a, "大盘过滤 开")

    print("\n########## B 组：关闭大盘环境层（对照 v1 行为） ##########")
    CONFIG["use_regime_filter"] = False
    batches_b = build_batches(cal, index_df, verbose=False)
    res_b = simulate(batches_b, cal)
    rep_b = report(res_b, index_df, batches_b, "大盘过滤 关")

    print("\n########## A/B 对照结论 ##########")
    print(f"开空仓层: {rep_a['total_ret'] * 100:+.1f}% / 回撤 {rep_a['mdd'] * 100:.1f}% / 空仓 {rep_a['skipped']} 次")
    print(f"关空仓层: {rep_b['total_ret'] * 100:+.1f}% / 回撤 {rep_b['mdd'] * 100:.1f}%")
    print("若 A 显著好于 B → 手册第一层的价值被数据支持；若差别不大 → 该层作用有限，诚实接受。")

    # SWEEP：参数敏感性（防"两个案例定终身"）
    print("\n########## SWEEP 参数网格（大盘层关闭, 与当前默认一致） ##########")
    print("增速阈值 × 回撤下限 → 总收益。结论若随参数剧烈波动 = 过拟合，不可信。")
    CONFIG["use_regime_filter"] = False
    base_growth, base_pb = CONFIG["min_profit_growth"], CONFIG["pullback_min"]
    for g in [30, 50, 80]:
        for pb in [10, 20, 30]:
            CONFIG["min_profit_growth"], CONFIG["pullback_min"] = g, pb
            batches = build_batches(cal, index_df, verbose=False)
            res = simulate(batches, cal)
            eq = pd.DataFrame(res["equity"], columns=["date", "equity"])
            tr = eq["equity"].iloc[-1] / CONFIG["initial_capital"] - 1
            mdd = max_drawdown(eq["equity"])
            print(f"  增速>={g}% 回撤>={pb}%: 总收益 {tr * 100:+.1f}%  回撤 {mdd * 100:.1f}%")
    CONFIG["min_profit_growth"], CONFIG["pullback_min"] = base_growth, base_pb

    print("\n提醒：仍有幸存者偏差与披露快照偏差，以上数字整体偏乐观，只看方向与相对比较。")





# ==================== prefetch.py ====================

# -*- coding: utf-8 -*-
"""并行预取 v2 回测所需的全部候选股日线, 写入 bt_cache/d_<code>_full.csv。
先跑本脚本, 再跑 six_layer_v2.py 即为纯本地回测。

用法: python3 -m prefetch
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


CACHE = CONFIG["cache_dir"]


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
    for year in range(START_YEAR, END_YEAR + 1):
        for period in CONFIG["report_periods"]:
            rep = get_report_data(year, period)
            if rep.empty:
                continue
            df = rep[rep["profit_yoy"] >= CONFIG["min_profit_growth"]]
            if CONFIG["exclude_st"]:
                df = df[~df["name"].astype(str).str.contains("ST|退", na=False)]
            cap = CONFIG["max_candidates_per_batch"]
            if cap and len(df) > cap:
                df = df.head(cap)
            codes.extend(df["code"].tolist())
    return sorted(set(codes))


def fetch_one(code):
    out = os.path.join(CACHE, f"d_{code}_full.csv")
    if os.path.exists(out):
        return code, "cached"
    df, src = _fetch_daily_any_source(code, INDEX_FETCH_START, f"{END_YEAR}1231")
    if df is None:
        return code, "FAIL"
    df = _normalize_daily(df)
    df = df[df["close"] > 0]
    df.to_csv(out, index=False)
    return code, src


def main_prefetch():
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


# ==================== entry_lab.py ====================

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


OUT = os.path.join(OUT_DIR, "candidates.csv")


def main_entry_lab():
    idx = get_index_daily()
    idx_dates = list(idx["date"])
    idx_close = idx["close"].values
    cal = [d for d in get_trade_cal()
           if f"{START_YEAR}0101" <= d <= f"{END_YEAR}1231"]

    rows = []
    n_batches = 0
    for year in range(START_YEAR, END_YEAR + 1):
        for period in CONFIG["report_periods"]:
            sd = batch_signal_date(cal, year, period)
            if not sd:
                continue
            n_batches += 1
            rep = get_report_data(year, period)
            if rep.empty:
                continue
            df = rep[rep["profit_yoy"] >= CONFIG["min_profit_growth"]]
            if CONFIG["exclude_st"]:
                df = df[~df["name"].astype(str).str.contains("ST|退", na=False)]
            sdt = pd.to_datetime(sd)
            i_idx = bisect.bisect_right(idx_dates, sdt) - 1
            if i_idx < 20:
                continue
            for _, r in df.iterrows():
                code = r["code"]
                full = load_full_daily(code)
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
                             if CONFIG["regime_ma"] else True,
                             **fwd})
            print("  %s%s 完成, 累计候选 %d" % (year, period, len(rows)), flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")
    print("\n写出 %s: %d 行, %d 个批次" % (OUT, len(out), n_batches))


# ==================== forward_edge.py ====================

# -*- coding: utf-8 -*-
"""基于 entry_lab 产出的事件数据, 检验各层预测力并对比候选入场规则。

用法: python3 -u -m forward_edge
"""
import os

import numpy as np
import pandas as pd


pd.set_option("display.width", 200)


def tstat(x):
    x = pd.Series(x).dropna()
    if len(x) < 3 or x.std() == 0:
        return np.nan
    return x.mean() / (x.std() / np.sqrt(len(x)))


def main_forward_edge():
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


# ==================== exit_lab.py ====================

# -*- coding: utf-8 -*-
"""卖出纪律 × 大盘层 交叉测试（在"均值回复入场"新规则下重做反事实）。

问题: 新入场买的是深回调/近期下跌股, 波动更大 → -4% 紧止损可能是主要杀手。
用法: OFFLINE=1 python3 -u -m exit_lab
"""
import os
import sys

import pandas as pd


BASE_KEYS = ("stop_loss_pct", "take_profit_1", "take_profit_2", "max_hold_days",
             "use_regime_filter")


def run(batches, cal, label, **over):
    for k in BASE_KEYS:
        CONFIG[k] = ORIG[k]
    CONFIG.update(over)
    res = simulate(batches, cal)
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
        "总收益%": round((eq.equity.iloc[-1] / CONFIG["initial_capital"] - 1) * 100, 1),
        "最大回撤%": round(max_drawdown(eq.equity) * 100, 1),
        "买入笔数": len(buys), "卖出腿数": len(tr) - len(buys),
        "止损腿数": int((tr.action == "stop_loss").sum()),
        "毛盈亏(元)": round(gross),
        "年化%": round(((eq.equity.iloc[-1] / CONFIG["initial_capital"])
                        ** (1 / 8.7) - 1) * 100, 1),
    }


ORIG = {k: CONFIG[k] for k in BASE_KEYS}


def main_exit_lab():
    idx = get_index_daily()
    cal = [d for d in get_trade_cal()
           if f"{START_YEAR}0101" <= d <= f"{END_YEAR}1231"]

    rows = []
    for regime in (True, False):
        tag = "大盘层开" if regime else "大盘层关"
        # 关键: 批次必须在对应的 regime 设置下重建, 否则 regime_ok 用的是旧值
        CONFIG["use_regime_filter"] = regime
        batches = build_batches(cal, idx, verbose=False)
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
    CONFIG["use_regime_filter"] = False
    batches = build_batches(cal, idx, verbose=False)
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
        CONFIG[k] = ORIG[k]
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    df.to_csv(os.path.join(OUT_DIR, "exit_lab.csv"), index=False, encoding="utf-8-sig")
    print("\n已存 exit_lab.csv")


# ==================== loss_analysis.py ====================

# -*- coding: utf-8 -*-
"""亏损归因分析: 把亏损拆成 选股能力 / 卖出纪律 / 成本 / 择时 四块。

用法: OFFLINE=1 python3 -u -m loss_analysis
"""
import os
import sys
from collections import defaultdict, deque

import numpy as np
import pandas as pd



def load():
    idx = get_index_daily()
    cal = [d for d in get_trade_cal()
           if f"{START_YEAR}0101" <= d <= f"{END_YEAR}1231"]
    batches = build_batches(cal, idx, verbose=False)
    res = simulate(batches, cal)
    tr = pd.DataFrame(res["trades"], columns=["date", "code", "action", "price", "shares"])
    tr["date"] = pd.to_datetime(tr["date"])
    eq = pd.DataFrame(res["equity"], columns=["date", "equity"])
    eq["date"] = pd.to_datetime(eq["date"])
    return idx, cal, batches, tr, eq


def section(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def main_loss_analysis():
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
    comm = sum(max(a * CONFIG["commission"], CONFIG["min_commission"])
               for a in list(buys.price * buys.shares) + list(sells.price * sells.shares))
    tax = sell_amt * CONFIG["stamp_tax"]
    slip = (buy_amt + sell_amt) * CONFIG["slippage"]
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
        s = get_daily(code, INDEX_FETCH_START, f"{END_YEAR}1231")
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
        s = get_daily(code, INDEX_FETCH_START, f"{END_YEAR}1231")
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
    base = {k: CONFIG[k] for k in ("stop_loss_pct", "take_profit_1",
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
        CONFIG.update(base)
        CONFIG.update(over)
        r = simulate(batches, cal)
        e = pd.DataFrame(r["equity"], columns=["date", "equity"])
        t = pd.DataFrame(r["trades"], columns=["date", "code", "action", "price", "shares"])
        sl = (t.action == "stop_loss").sum()
        rows.append({"卖出参数": name,
                     "总收益%": round((e.equity.iloc[-1] / CONFIG["initial_capital"] - 1) * 100, 1),
                     "最大回撤%": round(max_drawdown(e.equity) * 100, 1),
                     "止损腿数": sl, "卖出腿数": (t.action != "buy").sum()})
    CONFIG.update(base)
    print(pd.DataFrame(rows).to_string(index=False))


# ==================== freq_sweep.py ====================

# -*- coding: utf-8 -*-
"""交易频率对照: 同一套六层逻辑, 只改"频率相关"参数, 看笔数与绩效如何变化。

用法: OFFLINE=1 python3 -u -m freq_sweep
"""
import sys
import os

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
    CONFIG.update(base)

    index_df = get_index_daily()
    # regime_ma 变化需要重算均线
    index_df["ma"] = index_df["close"].rolling(CONFIG["regime_ma"]).mean()
    cal = [d for d in get_trade_cal() if f"{START_YEAR}0101" <= d <= f"{END_YEAR}1231"]

    batches = build_batches(cal, index_df, verbose=False)
    n_pick = sum(len(b["picks"]) for b in batches)
    n_skip = sum(1 for b in batches if not b["regime_ok"])
    res = simulate(batches, cal)
    tr = pd.DataFrame(res["trades"], columns=["date", "code", "action", "price", "shares"])
    eq = pd.DataFrame(res["equity"], columns=["date", "equity"])
    total = eq["equity"].iloc[-1] / CONFIG["initial_capital"] - 1
    mdd = max_drawdown(eq["equity"])

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


def main_freq_sweep():
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


# ==================== oos_split.py ====================

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
    saved = {k: CONFIG.get(k) for k in over}
    CONFIG.update(over)
    try:
        batches = build_batches(cal_all, index_df, verbose=False)
        out = {}
        for tag, cal in (("IS", cal_is), ("OOS", cal_oos)):
            res = simulate(batches, cal, liquidate_at_end=True)
            eq = pd.DataFrame(res["equity"], columns=["date", "equity"])
            tr = pd.DataFrame(res["trades"], columns=["date", "code", "action", "price", "shares"])
            ret = eq.equity.iloc[-1] / CONFIG["initial_capital"] - 1
            buys = tr[tr.action == "buy"]
            gross = 0.0
            for _, s in tr[tr.action != "buy"].iterrows():
                b = buys[(buys.code == s.code) & (buys.date <= s.date)]
                if not b.empty:
                    gross += (s.price - b.iloc[-1].price) * s.shares
            out[tag] = {
                "收益%": ret * 100,
                "回撤%": max_drawdown(eq.equity) * 100,
                "买入笔数": len(buys),
                "毛盈亏": gross,
            }
        return out
    finally:
        CONFIG.update(saved)


def main_oos_split():
    t0 = time.time()
    index_df = get_index_daily()
    cal_all = [d for d in get_trade_cal()
               if f"{START_YEAR}0101" <= d <= f"{END_YEAR}1231"]
    cal_is = [d for d in cal_all if d <= IS_END]
    cal_oos = [d for d in cal_all if d >= OOS_START]
    print("IS 交易日 %d (%s~%s), OOS 交易日 %d (%s~%s)" %
          (len(cal_is), cal_is[0], cal_is[-1], len(cal_oos), cal_oos[0], cal_oos[-1]))

    default = {k: CONFIG[k] for k in KEYS}
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


# ==================== incremental_test.py ====================

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


def main_incremental_test():
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


# ==================== stress_delist.py ====================

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


SAVE = ("delist_haircut", "delist_prob", "delist_loss", "stress_seed",
        "use_regime_filter")


def summarize(res, label):
    eq = pd.DataFrame(res["equity"], columns=["date", "equity"])
    tr = pd.DataFrame(res["trades"], columns=["date", "code", "action", "price", "shares"])
    ret = eq.equity.iloc[-1] / CONFIG["initial_capital"] - 1
    return {"场景": label,
            "总收益%": round(ret * 100, 1),
            "最大回撤%": round(max_drawdown(eq.equity) * 100, 1),
            "买入笔数": int((tr.action == "buy").sum()),
            "强平笔数": int((tr.action == "delist_exit").sum()),
            "注入退市笔数": res.get("n_doomed", 0)}


def main_stress_delist():
    idx = get_index_daily()
    cal = [d for d in get_trade_cal()
           if f"{START_YEAR}0101" <= d <= f"{END_YEAR}1231"]
    saved = {k: CONFIG[k] for k in SAVE}

    batches_off = None
    batches_on = None
    rows = []

    # A + B: 真实强平次数 与 惩罚档位(分别在大盘层开/关两种设置下)
    batches_by_regime = {}
    for regime in (False, True):
        CONFIG["use_regime_filter"] = regime
        batches = build_batches(cal, idx, verbose=False)
        batches_by_regime[regime] = batches
        tag = "大盘层开" if regime else "大盘层关"
        for hc in (0.0, 0.3, 0.5, 0.7):
            CONFIG["delist_haircut"] = hc
            CONFIG["delist_prob"] = 0.0
            res = simulate(batches, cal, liquidate_at_end=True)
            rows.append(summarize(res, "%s | 真实强平惩罚 -%.0f%%" % (tag, hc * 100)))
        CONFIG["delist_haircut"] = 0.0

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
                    CONFIG["delist_prob"] = p
                    CONFIG["delist_loss"] = loss
                    CONFIG["stress_seed"] = 20261010 + seed
                    res = simulate(batches, cal, liquidate_at_end=True)
                    eq = pd.DataFrame(res["equity"], columns=["date", "equity"])
                    rets.append(eq.equity.iloc[-1] / CONFIG["initial_capital"] - 1)
                    mdds.append(max_drawdown(eq.equity))
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

    CONFIG.update(saved)


# ==================== coverage_check.py ====================

# -*- coding: utf-8 -*-
"""覆盖率诊断: 候选池里有行情的比例有多少。

背景: 回测的候选池 = 业绩池(净利同比>=阈值, 去ST)。但免费数据源拿不到全部个股历史行情,
      缺的代码会被静默跳过。覆盖率不标注清楚, 结论就无法判断可信度。

输出: 每个报告期的 候选数 / 有行情数 / 覆盖率, 以及整体口径与"可补/不可补"拆分。
      结果写入 output/coverage.csv, 并导出可补清单 output/missing_codes.txt 供 prefetch 使用。

用法: OFFLINE=1 python3 -u coverage_check.py
"""
import os
import sys

import pandas as pd



def main_coverage_check():
    y = load_yjbb_local()
    have = set(pd.read_parquet(os.path.join(V1_DATA, "daily_all.parquet"),
                               columns=["code"])["code"].unique())
    rows, need = [], set()
    for (year, period), g in sorted(y.items()):
        cand = g[g["profit_yoy"] >= CONFIG["min_profit_growth"]]
        if CONFIG["exclude_st"]:
            cand = cand[~cand["name"].astype(str).str.contains("ST|退", na=False)]
        codes = set(cand["code"])
        need |= codes
        rows.append({"报告期": "%s%s" % (year, period), "候选数": len(codes),
                     "有行情": len(codes & have),
                     "覆盖率%": round(100 * len(codes & have) / max(1, len(codes)), 1)})
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT_DIR, "coverage.csv"), index=False, encoding="utf-8-sig")

    def is_bse(c):
        return c[0] in "489"

    miss = sorted(need - have)
    fixable = [c for c in miss if not is_bse(c)]
    print("=" * 84)
    print("候选池覆盖率诊断（阈值 净利同比>=%s%%, 已去ST）" % CONFIG["min_profit_growth"])
    print("=" * 84)
    print("业绩池候选(全报告期去重): %d 只" % len(need))
    print("  有行情: %d 只 = %.1f%%" % (len(need & have), 100 * len(need & have) / len(need)))
    print("  缺行情: %d 只" % len(miss))
    print("     其中北交所(4xx/8xx/9xx, 免费源不支持): %d 只" % (len(miss) - len(fixable)))
    print("     可补沪深股: %d 只  → 已导出 output/missing_codes.txt" % len(fixable))
    print("\n分报告期覆盖率（尾部 12 期）:")
    print(df.tail(12).to_string(index=False))
    print("\n按批次加权的覆盖率: %.1f%%" %
          (100 * df["有行情"].sum() / df["候选数"].sum()))
    with open(os.path.join(OUT_DIR, "missing_codes.txt"), "w") as f:
        f.write("\n".join(fixable))
    print("\n提醒: 覆盖率低 + 缺失非随机 → 选股结论的解释力受限, 报告结论时必须标注该数字。")

# ==================== 命令行入口 ====================
COMMANDS = {
    "core": ("核心回测(六层筛选+交易仿真+报告)", "run_core"),
    "prefetch": ("预取候选股日线(联网)", "main_prefetch"),
    "entry_lab": ("事件级数据: 候选特征+前瞻超额", "main_entry_lab"),
    "forward_edge": ("分层检验+入场规则对比", "main_forward_edge"),
    "exit_lab": ("卖出参数×大盘层交叉测试", "main_exit_lab"),
    "loss_analysis": ("亏损归因", "main_loss_analysis"),
    "freq_sweep": ("交易频率对照", "main_freq_sweep"),
    "oos_split": ("样本外切分: 2018-2023定参 → 2024-2026验证", "main_oos_split"),
    "incremental_test": ("增量检验: 六层过滤 vs 同池随机", "main_incremental_test"),
    "stress_delist": ("退市压力测试", "main_stress_delist"),
    "coverage_check": ("候选池覆盖率诊断", "main_coverage_check"),
}


def _usage():
    print("用法: python3 %s <command>" % os.path.basename(__file__))
    print("\n可用命令:")
    for k, (desc, _) in COMMANDS.items():
        print("  %-14s %s" % (k, desc))


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _usage()
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print("未知命令: %s" % cmd)
        _usage()
        sys.exit(1)
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    fn = globals()[COMMANDS[cmd][1]]
    fn()
