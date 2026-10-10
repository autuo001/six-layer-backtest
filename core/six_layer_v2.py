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
PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # …/six_layer_backtest
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


def run():
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


if __name__ == "__main__":
    run()
