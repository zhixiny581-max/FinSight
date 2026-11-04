# -*- coding: utf-8 -*-
"""iFinD 新闻接入诊断：定位「只有几天、条数少、当天没有」的原因。

用法：
    set IFIND_MCP_AUTHORIZATION=你的授权串
    python diag_news.py              # 探测最近 3 天，每个日期两种参数写法对比
    python diag_news.py --all-days    # 探测全部 7 天
    python diag_news.py --raw         # 额外打印原始返回片段

只做只读请求，不写文件、不改缓存、不影响正在运行的服务。
每次运行最多发起 3~7 组、每组 2 次 iFinD 调用，会消耗少量额度。
"""

import json
import os
import re
import sys
import time

import news_provider as np

DAY_KEYS = ("published_at", "title")
PROBE_KEYWORD = np.FIXED_DOMESTIC[0]


def probe(client, day, use_full_range):
    """对某一天发起一次 search_news，返回耗时与解析结果。"""
    if use_full_range:
        start, end = day + " 00:00:00", day + " 23:59:59"
    else:
        start, end = day, day
    args = {"query": PROBE_KEYWORD, "time_start": start, "time_end": end, "size": 20}
    started = time.monotonic()
    try:
        raw = client.call("news", "search_news", args, timeout=30)
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "elapsed": time.monotonic() - started,
                "error": str(error)[:80], "raw": ""}
    elapsed = time.monotonic() - started
    try:
        items = np.normalize_news_response(raw)
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "elapsed": elapsed, "error": "解析失败: " + str(error)[:60], "raw": ""}
    same_day = [item for item in items if item.get("published_at", "")[:10] == day]
    return {"ok": True, "elapsed": elapsed, "parsed": len(items), "same_day": len(same_day),
            "sample": [item.get("published_at", "(空)") for item in items[:3]],
            "titles": [item.get("title", "")[:22] for item in same_day[:2]],
            "raw": json.dumps(raw, ensure_ascii=False)[:280] if raw else ""}


def main():
    auth = (os.getenv("IFIND_MCP_AUTHORIZATION") or "").strip()
    show_raw = "--raw" in sys.argv
    all_days = "--all-days" in sys.argv
    if not auth or re.search(r"your.*(?:key|token)|这里粘贴", auth, re.I):
        print("未配置 IFIND_MCP_AUTHORIZATION，无法探测。")
        print("请在启动服务的同一个窗口先设置：")
        print("    set IFIND_MCP_AUTHORIZATION=你的授权串")
        return 1

    dates = np.recent_dates()
    targets = dates if all_days else dates[:3]
    client = np.IFindClient(auth)

    print("=" * 74)
    print("iFinD 新闻接入诊断")
    print("关键词：%s" % PROBE_KEYWORD)
    print("探测日期：%s" % "、".join(targets))
    print("=" * 74)

    rows = []
    for day in targets:
        print("\n[%s]" % day)
        plain = probe(client, day, False)
        full = probe(client, day, True)
        rows.append((day, plain, full))
        for label, result in (("现状 time_start=end=日期", plain), ("全时段 00:00:00~23:59:59", full)):
            if not result["ok"]:
                print("  %-26s 失败：%s（%.1fs）" % (label, result["error"], result["elapsed"]))
                continue
            print("  %-26s 返回 %2d 条，同日 %2d 条，耗时 %.2fs"
                  % (label, result["parsed"], result["same_day"], result["elapsed"]))
            if result["sample"]:
                print("  %-26s 时间样本：%s" % ("", " | ".join(result["sample"])))
            if result["titles"]:
                print("  %-26s 标题样本：%s" % ("", " / ".join(result["titles"])))
            if show_raw and result["raw"]:
                print("  %-26s 原始片段：%s" % ("", result["raw"]))

    # ---- 汇总判定 ----
    print("\n" + "=" * 74)
    print("判定")
    print("=" * 74)
    today_plain = rows[0][1]
    today_full = rows[0][2]
    if today_plain["ok"] and today_full["ok"]:
        if today_plain["parsed"] == 0 and today_full["parsed"] > 0:
            print("· 当天用「time_start=time_end=日期」返回 0 条，用全时段返回 %d 条。"
                  % today_full["parsed"])
            print("  => 根因：time_end 只传日期时被按当天 00:00:00 解释，当天区间为空。")
            print("     修法：把 time_end 改成 '<日期> 23:59:59'（后端 news_provider.py:657）。")
        elif today_plain["parsed"] == 0 and today_full["parsed"] == 0:
            print("· 当天两种写法都返回 0 条。")
            print("  => 不是参数问题，是数据源当天还没有收录，或关键词当天无匹配。")
        else:
            print("· 当天用现状写法就能返回 %d 条，参数语义正常。" % today_plain["parsed"])
        dropped = today_full["parsed"] - today_full["same_day"]
        if dropped > 0:
            print("· 当天有 %d 条被日期过滤丢掉（published_at 不是 %s 开头）。"
                  % (dropped, dates[0]))
            print("  => 这些条目的时间格式无法解析，或跨时区落到了相邻日期。")

    ok_rows = [row for row in rows if row[1]["ok"]]
    if ok_rows:
        avg = sum(row[1]["elapsed"] for row in ok_rows) / len(ok_rows)
        per_day = len(np.FIXED_DOMESTIC) + len(np.FIXED_INTERNATIONAL) + len(np.SUPPLEMENTAL)
        budget = 175.0
        reachable = budget / (avg * per_day) if avg > 0 else 0
        print("\n· 单次调用平均 %.2fs，每天最多 %d 个关键词。" % (avg, per_day))
        print("  抓取阶段总预算 175s，按此速度只能覆盖约 %.1f 天（共 7 天）。" % reachable)
        if reachable < 7:
            print("  => 抓取阶段就会在中途耗尽预算，后面几天进入 0 条；")
            print("     同时摘要阶段与抓取共用同一 175s 预算，新新闻来不及摘要也会被丢弃。")

    print("\n完成。以上结果可直接贴给负责数据接入的同学。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
