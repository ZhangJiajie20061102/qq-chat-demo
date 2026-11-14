# -*- coding: utf-8 -*-
"""
界面冒烟测试

用真实 tkinter 创建好友列表 / 聊天窗 / 搜索窗，走完「收到消息 -> 变红提醒 ->
点开聊天窗 -> 实时追加」整条链路。socket 用假的，不需要启动服务器。

用法：
    python tests/test_gui.py
退出码：0 全部通过，1 有失败
"""
import os
import sys
import time
import tkinter as tk
from tkinter import messagebox

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from friend_window import FriendWindow
from search_friend import SearchFriend
from chat_win import get_history

ok = 0
fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  [OK]   {name}")
    else:
        fail += 1
        print(f"  [FAIL] {name}  {detail}")


class FakeSk:
    """假的 socket：记录发出去的东西，recv 一直阻塞（模拟真实连接）"""

    def __init__(self):
        self.sent = []

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, n):
        time.sleep(30)
        return b""

    def close(self):
        pass


def pump(root, n=6):
    for _ in range(n):
        try:
            root.update()
        except tk.TclError:
            return
        time.sleep(0.03)


def main():
    # 拦截所有弹窗，避免测试卡在模态框
    asked = []
    shown = []
    orig_ask = messagebox.askokcancel
    orig_info = messagebox.showinfo
    orig_warn = messagebox.showwarning
    messagebox.askokcancel = lambda title=None, msg=None, **k: (asked.append(msg), True)[1]
    messagebox.showinfo = lambda title=None, msg=None, **k: (shown.append(msg), None)[1]
    messagebox.showwarning = lambda title=None, msg=None, **k: (shown.append(msg), None)[1]

    root = tk.Tk()
    root.withdraw()
    sk = FakeSk()

    try:
        print("【1】好友列表")
        fw = FriendWindow(root, sk, "123", "阿三", [
            {"qq_number": "qq助手", "nickname": "QQ助手", "online": True},
            {"qq_number": "456", "nickname": "小四", "online": False},
        ])
        pump(root)
        check("窗口创建成功", fw.win.winfo_exists() == 1)
        check("渲染出 2 个好友", len(fw.labels) == 2, list(fw.labels))
        check("在线好友显示深色", fw.labels["qq助手"].cget("fg") == "#333",
              fw.labels["qq助手"].cget("fg"))
        check("离线好友显示浅灰", fw.labels["456"].cget("fg") == "#999",
              fw.labels["456"].cget("fg"))
        check("底部显示当前账号", "123" in fw.hint.cget("text"), fw.hint.cget("text"))

        print("\n【2】搜索框过滤")
        fw.render("小四")
        pump(root)
        check("按昵称过滤只剩 1 个", len(fw.labels) == 1, list(fw.labels))
        check("过滤结果是 456", "456" in fw.labels)
        fw.render("")
        pump(root)
        check("清空过滤恢复 2 个", len(fw.labels) == 2)

        print("\n【3】收消息 / 未读闪烁")
        fw.handle_msg({"status": "other_chat_u", "src_id": "456",
                       "nickname": "小四", "chat_content": "在吗？我是小四"})
        pump(root)
        check("456 被标记为未读", "456" in fw.unread, fw.unread)
        check("未读名字变红", fw.labels["456"].cget("fg") == "#e24b4a",
              fw.labels["456"].cget("fg"))
        check("窗口没开时消息已存进历史",
              len(get_history("123", "456")) == 1, get_history("123", "456"))
        check("闪烁定时器已启动", fw.blink_job is not None)

        print("\n【4】点开聊天窗，消息实时显示")
        win = fw.open_chat("456")
        pump(root, 10)
        check("聊天窗创建成功", win.winfo_exists() == 1)
        check("点开后未读被清除", "456" not in fw.unread, fw.unread)
        check("名字颜色恢复", fw.labels["456"].cget("fg") == "#999",
              fw.labels["456"].cget("fg"))
        check("历史消息显示到窗口里", len(win._bubbles) == 1, len(win._bubbles))
        check("窗口标题带对方昵称", "小四" in win.title(), win.title())

        # 窗口开着时再来一条 -> 应该立刻追加
        fw.handle_msg({"status": "other_chat_u", "src_id": "456",
                       "nickname": "小四", "chat_content": "第二条"})
        pump(root)
        check("开着窗口时实时追加", len(win._bubbles) == 2, len(win._bubbles))
        check("窗口开着不再标未读", "456" not in fw.unread, fw.unread)

        print("\n【5】发送消息（协议格式）")
        win.input_text.insert("1.0", "在，什么事")
        win.send_message()
        pump(root)
        sent = b"".join(sk.sent).decode("utf-8")
        check("发出了 start_chat 包", '"status": "start_chat"' in sent, sent[-200:])
        check("包里有 dst_id=456", '"dst_id": "456"' in sent, sent[-200:])
        check("包里有消息内容", "在，什么事" in sent)
        check("自己发的也显示在窗口", len(win._bubbles) == 3, len(win._bubbles))

        print("\n【6】关掉再开，历史还在")
        win._on_close()
        pump(root)
        win2 = fw.open_chat("456")
        pump(root, 10)
        check("重新打开历史 3 条都在", len(win2._bubbles) == 3, len(win2._bubbles))

        print("\n【7】添加好友窗口")
        dlg = SearchFriend(fw.win, sk, "123")
        fw.search_dlg = dlg
        pump(root)
        check("搜索窗创建成功", dlg.win.winfo_exists() == 1)
        check("搜索窗不阻塞好友列表（Toplevel）", str(dlg.win.winfo_class()) == "Toplevel",
              dlg.win.winfo_class())

        dlg.entry.insert(0, "789")
        dlg.search_user()
        pump(root)
        sent = b"".join(sk.sent).decode("utf-8")
        check("发出 search_frd_exist", "search_frd_exist" in sent, sent[-200:])
        check("搜索中按钮被禁用", str(dlg.search_button.cget("state")) == "disabled")

        # 服务器结果回来
        fw.handle_msg({"status": "search_result", "found": True, "qq_number": "789",
                       "nickname": "小五", "online": True, "reason": ""})
        pump(root)
        check("找到人后显示添加按钮", dlg.add_button.winfo_manager() == "pack",
              dlg.add_button.winfo_manager())
        check("结果文字带昵称", "小五" in dlg.result_label.cget("text"),
              dlg.result_label.cget("text"))

        dlg.add_friend()
        pump(root)
        sent = b"".join(sk.sent).decode("utf-8")
        check("发出 add_frd_command", "add_frd_command" in sent, sent[-200:])
        check("发过后按钮变成已发送", "已发送" in dlg.add_button.cget("text"))

        print("\n【8】别人加你：同意流程")
        fw.handle_msg({"status": "other_add_u", "qq_number": "789", "nickname": "小五"})
        pump(root)
        check("弹了确认框", len(asked) == 1, asked)
        sent = b"".join(sk.sent).decode("utf-8")
        check("同意后发出 acpt_frd_request", "acpt_frd_request" in sent, sent[-200:])
        check("请求里带对方 QQ", '"beitongyi_qq_number": "789"' in sent, sent[-200:])

        print("\n【9】好友列表刷新")
        fw.handle_msg({"status": "acpt_ok", "friends": [
            {"qq_number": "qq助手", "nickname": "QQ助手", "online": True},
            {"qq_number": "456", "nickname": "小四", "online": False},
            {"qq_number": "789", "nickname": "小五", "online": True},
        ]})
        pump(root)
        check("列表变成 3 个", len(fw.labels) == 3, list(fw.labels))
        check("新好友 789 在列表里", "789" in fw.labels)

        print("\n【10】错误提示与断开")
        fw.handle_msg({"status": "error", "msg": "789 不在线，消息没发出去"})
        pump(root)
        check("error 弹出提示", any("不在线" in s for s in shown), shown)
        fw.handle_msg({"status": "__disconnected__"})
        pump(root)
        check("断开提示写到底部", "断开" in fw.hint.cget("text"), fw.hint.cget("text"))

        print("\n【11】关闭窗口")
        fw.close()
        pump(root)
        check("close 后窗口销毁", not fw.win.winfo_exists())
        check("收消息线程已停止", fw._stop.is_set())

    finally:
        messagebox.askokcancel = orig_ask
        messagebox.showinfo = orig_info
        messagebox.showwarning = orig_warn
        try:
            root.destroy()
        except tk.TclError:
            pass

    print("\n" + "=" * 56)
    print(f"结果：{ok} 项通过，{fail} 项失败")
    print("=" * 56)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
