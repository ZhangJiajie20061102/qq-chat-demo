# -*- coding: utf-8 -*-
"""
search_friend.py —— 查找添加好友窗口（笔记 04）

和笔记原版的三处不同：
1. 用 tk.Toplevel 而不是 tk.Tk()：笔记原版 new 了一个独立的 Tk 再 mainloop()，
   会把好友列表整个卡住（必须关掉搜索窗，好友列表才响应）。
2. 不用自己 recv：搜索结果由好友列表的收消息线程统一收到，再回调 show_result()。
   否则搜索窗和好友列表抢同一个 socket，谁都收不全。
3. 添加按钮点过之后禁用，避免重复发申请。
"""

import json
import tkinter as tk
from tkinter import messagebox


def _pack(obj):
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


class SearchFriend:
    """在好友列表里点「＋ 添加好友」弹出来的窗口"""

    def __init__(self, parent, con_sk, my_usr_id, on_result=None):
        self.con_sk = con_sk
        self.my_usr_id = my_usr_id
        self.on_result = on_result

        self.target = ""            # 当前搜索/要添加的 QQ 号
        self.found_user = None      # 服务器确认存在的对象

        self.win = tk.Toplevel(parent)
        self.win.title("查找添加好友")
        self.win.geometry("340x230")
        self.win.resizable(False, False)
        self.win.configure(bg="#f5f6fa")
        self.win.transient(parent)
        self.center(parent)

        self.build_ui()

    def center(self, parent):
        self.win.update_idletasks()
        try:
            x = parent.winfo_rootx() + (parent.winfo_width() - 340) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - 230) // 2
        except tk.TclError:
            x = y = 200
        self.win.geometry(f"340x230+{max(x, 0)}+{max(y, 0)}")

    def build_ui(self):
        top = tk.Frame(self.win, bg="#12b7f5", height=48)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Label(top, text="查找添加好友", font=("微软雅黑", 13, "bold"),
                 fg="white", bg="#12b7f5").pack(pady=12)

        body = tk.Frame(self.win, bg="#f5f6fa")
        body.pack(fill="both", expand=True, padx=20, pady=14)

        row = tk.Frame(body, bg="#f5f6fa")
        row.pack(pady=(4, 10))
        tk.Label(row, text="QQ号", font=("微软雅黑", 10),
                 bg="#f5f6fa", fg="#666").pack(side="left", padx=(0, 6))

        self.entry = tk.Entry(row, width=16, font=("微软雅黑", 11), relief="flat",
                              highlightthickness=1, highlightbackground="#dcdde1",
                              highlightcolor="#12b7f5")
        self.entry.pack(side="left", ipady=5)
        self.entry.bind("<Return>", lambda e: self.search_user())

        self.search_button = tk.Button(row, text="搜索", font=("微软雅黑", 10),
                                       bg="#12b7f5", fg="white", relief="flat",
                                       cursor="hand2",
                                       activebackground="#0aa5e0",
                                       activeforeground="white",
                                       command=self.search_user)
        self.search_button.pack(side="left", padx=6, ipady=2)

        self.result_label = tk.Label(body, text="输入对方的 QQ 号，点搜索",
                                     font=("微软雅黑", 10), bg="#f5f6fa", fg="#999",
                                     wraplength=280, justify="center")
        self.result_label.pack(pady=6)

        # 添加按钮：找到人之后才显示
        self.add_button = tk.Button(body, text="添加好友", font=("微软雅黑", 11, "bold"),
                                    bg="#27ae60", fg="white", relief="flat",
                                    cursor="hand2",
                                    activebackground="#1e8b4d",
                                    activeforeground="white",
                                    command=self.add_friend)

    # ---------- 搜索 ----------
    def search_user(self):
        target = self.entry.get().strip()
        if not target:
            self.result_label.config(text="请先输入 QQ 号", fg="#a32d2d")
            return

        self.target = target
        self.found_user = None
        self.add_button.pack_forget()
        self.result_label.config(text=f"正在查找 {target} ...", fg="#888")
        self.search_button.config(state="disabled")

        # 请求由好友列表的收消息线程统一接，结果会回调 show_result
        try:
            self.con_sk.sendall(_pack({
                "status": "search_frd_exist",
                "qq_number": self.my_usr_id,
                "search_dst_id": target,
            }))
        except OSError as e:
            self.search_button.config(state="normal")
            self.result_label.config(text=f"发送失败：{e}", fg="#a32d2d")

    # ---------- 由 FriendWindow 收到 search_result 后调用 ----------
    def show_result(self, msg):
        self.search_button.config(state="normal")

        if msg.get("found"):
            self.found_user = msg
            nick = msg.get("nickname") or msg.get("qq_number")
            online = "在线" if msg.get("online") else "离线"
            self.result_label.config(
                text=f"找到用户：{msg.get('qq_number')}\n昵称：{nick}（{online}）",
                fg="#3b6d11")
            self.add_button.pack(pady=4)
        else:
            self.found_user = None
            self.add_button.pack_forget()
            self.result_label.config(
                text=msg.get("reason") or "未找到该用户", fg="#a32d2d")

    # ---------- 添加 ----------
    def add_friend(self):
        if not self.target:
            return
        try:
            self.con_sk.sendall(_pack({
                "status": "add_frd_command",
                "qq_number": self.my_usr_id,
                "search_dst_id": self.target,
            }))
        except OSError as e:
            messagebox.showerror("发送失败", str(e), parent=self.win)
            return

        self.add_button.config(state="disabled", text="已发送")
        self.result_label.config(
            text=f"好友申请已发给 {self.target}\n对方同意后会自动出现在好友列表",
            fg="#888")

    def close(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass
