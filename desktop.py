"""MEMCORE v6.0 · 桌面版启动入口

运行：python desktop.py
行为：
  1. 先探 127.0.0.1:8756 是否已有实例；有就直接开窗，不起第二个进程。
  2. 否则在后台线程拉起 uvicorn，轮询 /api/health 等它真就绪（不靠 sleep 猜时间）。
  3. pywebview 开原生窗口；WebView2 缺失时退回系统浏览器，服务继续跑。

参数：python desktop.py --browser   # 强制用浏览器打开
"""

import argparse
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

import uvicorn

PORT = 8756
HOST = "127.0.0.1"
URL = f"http://{HOST}:{PORT}"


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((HOST, port)) == 0


def server_ready(timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{URL}/api/health", timeout=1.0) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def serve():
    from server import app
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", action="store_true", help="用系统浏览器打开而不是原生窗口")
    args = ap.parse_args()

    started_here = False
    if not port_in_use(PORT):
        threading.Thread(target=serve, daemon=True).start()
        started_here = True

    if not server_ready():
        print(f"[MEMCORE] 后端没起来：{URL}/api/health 无响应。")
        print("排查：在工程目录跑 `python -m uvicorn server:app --port 8756` 看报错。")
        sys.exit(1)

    if args.browser:
        webbrowser.open(URL)
        print(f"[MEMCORE] 已用浏览器打开 {URL}（Ctrl+C 结束服务）")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return

    try:
        import webview
    except ImportError:
        webview = None

    if webview is None:
        webbrowser.open(URL)
        print(f"[MEMCORE] 未装 pywebview，已用系统浏览器打开 {URL}")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return

    try:
        window = webview.create_window(
            "MEMCORE v6.0 · Memory Field Engine",
            URL,
            width=1440,
            height=940,
            min_size=(1080, 640),
            resizable=True,
        )
        webview.start()
    except Exception as e:
        print(f"[MEMCORE] 原生窗口打不开（{e}），退回系统浏览器。")
        webbrowser.open(URL)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    finally:
        # 窗口关闭后进程退出，守护线程里的 uvicorn 随之结束
        if started_here:
            print("[MEMCORE] 窗口已关闭，服务结束。")


if __name__ == "__main__":
    main()
