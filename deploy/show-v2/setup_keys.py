# -*- coding: utf-8 -*-
"""命令行设置用户级 API 凭据（写 ~/.finsight/config.json）。

用法：
    双击 设置密钥.cmd      （推荐）
    python setup_keys.py    （命令行）

说明：
    这是"跨项目"的个人配置，优先级低于项目内的 api-config.json。
    如果只是本机部署这个项目，直接改 deploy/show-v2/api-config.json 更简单
    （双击「打开配置文件.cmd」即可）。

过程：逐项提示粘贴，直接回车保留原值，输入 - 清除该项。
页面不提供写入能力，凭据只能通过本脚本或配置文件落地，公网无法篡改。
"""

import sys

import config_store


def ask(current, masked):
    if current:
        print("      当前：%s" % masked)
        hint = "粘贴新值，直接回车保留，输入 - 清除"
    else:
        hint = "粘贴新值，直接回车跳过"
    try:
        value = input("      %s：" % hint).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return current, False
    if value == "-":
        return "", True
    if not value:
        return current, False
    return value, True


def main():
    saved = config_store.read_user()
    project = config_store.read_project()
    paths = config_store.paths()

    print("=" * 62)
    print("FinSight 接口凭据设置（用户级）")
    print("=" * 62)
    print("写入位置：%s" % paths["user"])
    print("（该文件在项目目录之外，不会随项目提交或打包）")
    print()
    if project:
        print("注意：项目内已存在 api-config.json（%d 项），" % len(project))
        print("      它的优先级高于这里，同名项会被项目文件覆盖。")
        print("      只想改本项目的密钥，请双击「打开配置文件.cmd」。")
        print()
    print("提示：粘贴时内容会明文显示，请确认周围无人；")
    print("      在教室公用电脑上使用后，可再次运行并输入 - 清除。")
    print()

    values = dict(saved)
    changed = False
    total = len(config_store.SECRET_FIELDS)
    for index, key in enumerate(config_store.SECRET_FIELDS, 1):
        meta = config_store.FIELDS[key]
        current = str(values.get(key) or "")
        print("[%d/%d] %s%s" % (index, total, meta["label"],
                                "（可选）" if meta.get("optional") else ""))
        new_value, touched = ask(current, config_store.masked(current))
        if touched:
            values[key] = new_value
            changed = True
        print()

    if not changed:
        print("没有改动。")
    else:
        config_store.write(values)
        print("已保存。")
        ready = [key for key, value in values.items() if str(value or "").strip()]
        print("当前已配置：%s" % ("、".join(ready) if ready else "无"))
    print()
    print("-" * 62)
    print("下一步：双击「启动展示站.cmd」启动服务，")
    print("        然后在页面左侧「工具 - 接口设置」点「全部检测」确认连通。")
    print("-" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
