# -*- coding: utf-8 -*-
"""FinSight 本地启动器（由「启动展示站.cmd」调用）。

为什么单独写一个 Python 启动器而不是全靠批处理：
  批处理里处理带空格的路径、中文路径、嵌套引号非常容易出错，
  而"找到 Python 之后要做什么"本来就是 Python 更擅长的事。
  这个文件只负责三件事：定端口、延时打开浏览器、启动服务。

用法：
    python -B run_local.py          # 默认 8765
    python -B run_local.py 8767     # 指定端口
"""

import os
import socket
import sys
import threading
import webbrowser


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main():
    port = 8765
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])

    here = os.path.dirname(os.path.abspath(__file__))
    os.chdir(here)

    # 必要的模块自检，缺文件时给出明确提示而不是抛栈
    for name in ("app.py", "base.py", "popularity.py"):
        if not os.path.exists(os.path.join(here, name)):
            print("  [错误] 缺少 %s，请确认文件完整。" % name)
            return 1

    url = "http://127.0.0.1:%d/core" % port

    if port_in_use(port):
        print("  [提示] 端口 %d 已被占用。" % port)
        print("  如果 FinSight 已经在运行，直接打开下面地址即可：")
        print("    %s" % url)
        print()
        print("  如果占用者是别的程序，请换一个端口，例如：")
        print("    启动展示站.cmd 8767")
        print()
        try:
            webbrowser.open(url)
        except Exception:
            pass
        return 0

    print("  服务地址: %s" % url)
    print("  接口自检: http://127.0.0.1:%d/api/rank?limit=20" % port)

    # 凭据自检：没配置就先说清楚怎么办，省得进了页面才发现全是示例数据
    try:
        import config_store

        paths = config_store.paths()
        filled = [key for key, value in config_store.read().items() if value]
        if filled:
            print("  接口配置: 已读取 %d 项（%s）" % (len(filled), "、".join(filled)))
        elif paths["projectExists"]:
            print("  [提示] api-config.json 已存在但没有填值，补全后重新启动即可。")
        else:
            print("  [提示] 还没有接口配置，页面会显示示例数据。")
            print("        需要真实数据：双击「打开配置文件.cmd」填写 api-config.json")
    except Exception:
        pass

    print()
    print("  正在启动，浏览器稍后自动打开…")
    print("  关闭本窗口即停止服务。")
    print()

    # 给服务 2.5 秒启动时间，再打开浏览器，避免出现"无法访问"
    threading.Timer(2.5, lambda: webbrowser.open(url)).start()

    os.environ["PORT"] = str(port)
    os.environ.setdefault("DATA_DIR", os.path.join(here, "data"))

    import runpy
    runpy.run_path(os.path.join(here, "app.py"), run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
