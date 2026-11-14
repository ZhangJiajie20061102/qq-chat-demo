# -*- coding: utf-8 -*-
"""
main.py —— 登录界面（双击运行这个文件）

流程（笔记 03 的核心）：
    点「登 录」-> login() 打包 {status:"login", qq_number, password} 发给服务器
              -> 收一条 {status:"login_ok", nickname, friends}
              -> 藏起登录窗，把「这条已经登录的 socket + QQ号 + 昵称 + 好友列表」交给 FriendWindow
    注意：socket 不能关，好友列表和聊天窗都要复用它。
"""

import json
import os
import socket
import tkinter as tk
from tkinter import messagebox

from regi import RegisterWindow
from friend_window import FriendWindow

SERVER_HOST = os.environ.get("CHAT_HOST", "127.0.0.1")
SERVER_PORT = int(os.environ.get("CHAT_PORT", "8999"))


class LoginWindow:
    """模仿 QQ 的登录界面"""

    def __init__(self, root):
        self.root = root
        self.root.title("QQ 登录")
        self.root.resizable(False, False)
        self.root.configure(bg="#f5f6fa")
        self.center(400, 480)
        self.build_ui()

    def center(self, w, h):
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def build_ui(self):
        # ---------- 顶部 ----------
        top = tk.Frame(self.root, bg="#12b7f5", height=140)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Label(top, text="QQ", font=("微软雅黑", 34, "bold"),
                 fg="white", bg="#12b7f5").pack(pady=(22, 0))
        tk.Label(top, text="欢迎登录", font=("微软雅黑", 11),
                 fg="white", bg="#12b7f5").pack()

        # ---------- 表单 ----------
        form = tk.Frame(self.root, bg="#f5f6fa")
        form.pack(fill="both", expand=True, padx=42, pady=26)

        self.entry_user = self._field(form, "账号")
        self.entry_pwd = self._field(form, "密码", show="*")

        tk.Button(form, text="登 录", font=("微软雅黑", 12, "bold"),
                  bg="#12b7f5", fg="white",
                  activebackground="#0aa5e0", activeforeground="white",
                  relief="flat", cursor="hand2",
                  command=self.login).pack(fill="x", ipady=7, pady=(16, 10))

        tk.Button(form, text="注册新账号", font=("微软雅黑", 10),
                  bg="#f5f6fa", fg="#12b7f5", bd=0,
                  activebackground="#f5f6fa", activeforeground="#0aa5e0",
                  cursor="hand2",
                  command=self.open_register).pack()

        tk.Label(form, text=f"服务器 {SERVER_HOST}:{SERVER_PORT}",
                 font=("微软雅黑", 8), bg="#f5f6fa", fg="#bbb").pack(pady=(14, 0))

    def _field(self, parent, label, show=""):
        tk.Label(parent, text=label, font=("微软雅黑", 10),
                 bg="#f5f6fa", fg="#666").pack(anchor="w")
        entry = tk.Entry(parent, font=("微软雅黑", 11), relief="flat",
                         bg="white", show=show, highlightthickness=1,
                         highlightbackground="#dcdde1",
                         highlightcolor="#12b7f5")
        entry.pack(fill="x", ipady=7, pady=(5, 14))
        return entry

    # ---------- 事件 ----------
    def login(self):
        user = self.entry_user.get().strip()
        pwd = self.entry_pwd.get().strip()

        # 先本地校验，不通过就不连服务器（笔记原版是先 __init__ 里连了才判断空）
        if not user or not pwd:
            messagebox.showwarning("提示", "请输入账号和密码", parent=self.root)
            return

        # ---------- 1. 连服务器 ----------
        try:
            sk = socket.socket()
            sk.settimeout(5)
            sk.connect((SERVER_HOST, SERVER_PORT))
        except OSError as e:
            messagebox.showerror(
                "连接失败",
                f"连不上服务器 {SERVER_HOST}:{SERVER_PORT}\n\n"
                f"请先在 PyCharm 里运行 server.py\n\n{e}",
                parent=self.root)
            return

        # ---------- 2. 发登录包，等一条回复 ----------
        try:
            req = {"status": "login", "qq_number": user, "password": pwd}
            sk.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))

            buf = b""
            while b"\n" not in buf:
                data = sk.recv(4096)
                if not data:
                    raise OSError("服务器关闭了连接")
                buf += data
            reply = json.loads(buf.split(b"\n")[0].decode("utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            sk.close()
            messagebox.showerror("登录失败", f"与服务器通信出错：{e}", parent=self.root)
            return

        # ---------- 3. 判断结果 ----------
        if reply.get("status") != "login_ok":
            sk.close()
            messagebox.showerror("登录失败", reply.get("reason", "账号或密码错误"),
                                 parent=self.root)
            return

        # ---------- 4. 交接给好友列表 ----------
        sk.settimeout(None)          # 后面要长期阻塞收消息，5 秒超时必须清掉
        self.root.withdraw()         # 藏起登录窗（不销毁，它是主窗口）
        FriendWindow(
            self.root,
            sk,
            reply["qq_number"],
            reply.get("nickname", reply["qq_number"]),
            reply.get("friends", []),
            on_close=self.root.deiconify,    # 关掉好友列表后回到登录窗
        )

    def open_register(self):
        RegisterWindow(self.root)


if __name__ == "__main__":
    root = tk.Tk()
    LoginWindow(root)
    root.mainloop()
