# -*- coding: utf-8 -*-
"""一键准备并打开 api-config.json。

首次运行：复制 api-config.example.json 为 api-config.json
然后运行：用系统默认程序打开它，让使用者直接填写

用法：
    双击 打开配置文件.cmd      （推荐）
    python open_config.py      （命令行）
"""

import os
import shutil
import sys

import config_store


def main():
    target = config_store.PROJECT_FILE
    example = config_store.PROJECT_EXAMPLE

    print("=" * 62)
    print("FinSight 接口配置文件")
    print("=" * 62)
    print("文件位置：%s" % target)
    print()

    if target.is_file():
        print("已存在，直接打开。")
    elif example.is_file():
        shutil.copyfile(example, target)
        print("已从模板生成 api-config.json。")
    else:
        target.write_text('{\n  "ifind": "",\n  "deepseek": "",\n  "tavily": ""\n}\n',
                          encoding="utf-8")
        print("模板缺失，已生成一个空配置。")

    print()
    print("填写提示：")
    print("  · 只填你有权限使用的项，留空表示不配置")
    print("  · 值放在英文双引号里，例如  \"deepseek\": \"sk-xxxxxxxx\"")
    print("  · 不要改动左边的字段名")
    print("  · 这个文件不会被提交到 GitHub，也不会打进上传包")
    print()
    print("填完保存并关闭记事本，然后双击「启动展示站.cmd」。")
    print("启动后在页面左侧「工具 → 接口设置」点「全部检测」确认连通。")
    print("-" * 62)

    try:
        if hasattr(os, "startfile"):
            os.startfile(str(target))  # noqa: S606 - Windows 下用默认程序打开
        else:
            print("请手动打开上面这个文件。")
    except OSError as exc:
        print("自动打开失败（%s），请手动打开上面这个文件。" % type(exc).__name__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
