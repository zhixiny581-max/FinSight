# -*- coding: utf-8 -*-
"""命令行测试：抓取东方财富 A 股人气榜并打印结果。

用法：
    python test_rank.py            # 取前 20
    python test_rank.py 10         # 取前 10
    python test_rank.py 20 --raw   # 同时打印原始 JSON

只做只读请求，不写文件，不缓存。
"""

import json
import sys

import popularity


def main():
    limit = 20
    raw = "--raw" in sys.argv
    for arg in sys.argv[1:]:
        if arg.isdigit():
            limit = int(arg)
            break

    print("请求东方财富人气榜（前 %d 名）..." % limit)
    print("-" * 62)
    try:
        data = popularity.fetch_rank(limit)
    except popularity.RankError as error:
        hints = {
            "RANK_TIMEOUT": "接口响应超时。请检查网络，或稍后重试。",
            "RANK_UNREACHABLE": "无法连接 eastmoney.com。可能有代理/防火墙拦截，或需要关闭系统代理。",
            "RANK_HTTP": "接口返回了异常 HTTP 状态，可能被限流。",
            "RANK_PARSE": "返回内容不是预期 JSON，接口可能改版。",
            "RANK_REJECTED": "接口拒绝了请求参数，接口可能改版。",
            "RANK_EMPTY": "返回榜单为空。",
        }
        print("失败：%s" % error.code)
        print(hints.get(error.code, "未知错误。"))
        if error.detail:
            print("细节：%s" % error.detail)
        return 1

    print("更新时间：%s" % data["updatedAtText"])
    print("数据来源：%s" % data["source"])
    print("条数：%d" % len(data["items"]))
    print("-" * 62)
    print("%-4s %-10s %-8s %9s %9s" % ("排名", "名称", "代码", "最新价", "涨跌幅"))
    print("-" * 62)
    for item in data["items"]:
        price = item["price"]
        change = item["changePct"]
        price_text = ("%.2f" % price) if isinstance(price, (int, float)) else "—"
        if isinstance(change, (int, float)):
            change_text = "%+.2f%%" % change
        else:
            change_text = "—"
        name = item["name"] or "(未取得)"
        print("%-4s %-10s %-8s %9s %9s" % (item["rank"], name, item["code"], price_text, change_text))
    print("-" * 62)
    print(data["note"])

    if raw:
        print()
        print("原始 JSON：")
        print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
