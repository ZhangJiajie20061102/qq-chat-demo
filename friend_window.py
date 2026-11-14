# -*- coding: utf-8 -*-
"""
friend_window.py —— 好友列表（笔记 03 + 04 + 05 三篇的交汇点）

这个窗口承担四件事：
    1. 显示好友列表（昵称 + QQ + 在线状态），数据来自服务器的 login_ok / friends
    2. 一个收消息线程，处理服务器推过来的一切：好友申请、申请通过、聊天消息
    3. 「＋ 添加好友」打开 SearchFriend
    4. 点好友打开聊天窗；对方发来消息时，名字变红闪烁，点开后停止

三个必须注意的坑（笔记原版都踩了）：
    ① tkinter 不是线程安全的：收包在子线程，但改界面必须回到主线程。
       这里用 queue.Queue + after(80) 轮询，绝不在子线程里碰控件。
    ② 收消息线程必须等界面建好再启动，否则第一个包进来时 self.win 还不存在。
    ③ 一个好友一个聊天窗（字典存），不能用单个 self.chat_window，
       否则 A 的消息会显示到 B 的窗口里。
"""

import json
import queue
import threading
import tkinter as tk
from tkinter import messagebox

from chat_win import ChatWindow, remember
from search_friend import SearchFriend

BLUE = "#12b7f5"
BG = "#f5f6fa"
PALETTE = ["#12b7f5", "#f39c12", "#e84393", "#27ae60",
           "#8e44ad", "#d35400", "#34495e", "#16a085"]


def _color_for(name):
    """根据名字稳定地取一个头像颜色"""
    if not name:
        return PALETTE[0]
    return PALETTE[sum(ord(c) for c in name) % len(PALETTE)]


def _pack(obj):
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


class FriendWindow:
    """仿 QQ 的好友列表窗口"""

    def __init__(self, parent, con_sk, usr_id, nickname, friends, on_close=None):
        self.con_sk = con_sk
        self.usr_id = str(usr_id)
        self.nickname = nickname or self.usr_id
        self.on_close = on_close

        self.friends = list(friends or [])
        self.nick_map = {f["qq_number"]: f.get("nickname", f["qq_number"])
                         for f in self.friends}

        self.chat_windows = {}      # {QQ号: ChatWindow}  一人一个窗口
        self.search_dlg = None
        self.unread = set()         # 未读好友的 QQ 号
        self.labels = {}            # {QQ号: 名字 Label}  闪烁用
        self.blink_job = None
        self._blink_on = False
        self._dialog_open = False

        self.q = queue.Queue()
        self._stop = threading.Event()

        self.win = tk.Toplevel(parent)
        self.win.title(f"QQ · {self.nickname}")
        self.win.resizable(False, False)
        self.win.configure(bg=BG)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.center(380, 640)

        self.build_ui()

        # 界面建完才启动收消息线程（笔记原版在 build_ui 之前启动，第一个包会崩）
        threading.Thread(target=self.recv_loop, daemon=True).start()
        self.win.after(80, self.poll_queue)

    def center(self, w, h):
        x = (self.win.winfo_screenwidth() - w) // 2
        y = (self.win.winfo_screenheight() - h) // 2
        self.win.geometry(f"{w}x{h}+{x}+{y}")

    # ==================== 界面 ====================
    def build_ui(self):
        # ---------- 顶部 ----------
        top = tk.Frame(self.win, bg=BLUE, height=100)
        top.pack(fill="x")
        top.pack_propagate(False)

        tk.Label(top, text=self.nickname, font=("微软雅黑", 15, "bold"),
                 fg="white", bg=BLUE).pack(pady=(10, 0))
        tk.Label(top, text=f"QQ {self.usr_id}", font=("微软雅黑", 9),
                 fg="#d9f0ff", bg=BLUE).pack()

        self.search_var = tk.StringVar()
        search = tk.Entry(top, textvariable=self.search_var, font=("微软雅黑", 10),
                          relief="flat", bg="#e6f7ff")
        search.pack(fill="x", padx=16, pady=(6, 8), ipady=5)
        search.bind("<KeyRelease>", lambda e: self.render(self.search_var.get()))

        # ---------- 好友列表（可滚动） ----------
        container = tk.Frame(self.win, bg=BG)
        container.pack(fill="both", expand=True, padx=8, pady=8)

        self.canvas = tk.Canvas(container, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient="vertical",
                                 command=self.canvas.yview)
        self.list_frame = tk.Frame(self.canvas, bg=BG)

        self.window_id = self.canvas.create_window((0, 0), window=self.list_frame,
                                                   anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.list_frame.grid_columnconfigure(0, weight=1)
        self.list_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self.window_id, width=e.width))
        self.win.bind("<MouseWheel>", self._on_wheel)

        # ---------- 底部 ----------
        bottom = tk.Frame(self.win, bg="white", height=46)
        bottom.pack(fill="x")
        bottom.pack_propagate(False)

        self.hint = tk.Label(bottom, text=f"当前账号：{self.usr_id}",
                             font=("微软雅黑", 9), bg="white", fg="#999")
        self.hint.pack(side="left", padx=14)

        tk.Button(bottom, text="＋ 添加好友", font=("微软雅黑", 10),
                  bg=BLUE, fg="white", relief="flat", cursor="hand2",
                  activebackground="#0aa5e0", activeforeground="white",
                  command=self.open_add_friend).pack(side="right", padx=12, pady=8)

        self.render()

    # ==================== 列表渲染 ====================
    def render(self, keyword=""):
        self.labels.clear()          # 防止引用已销毁的控件
        for w in self.list_frame.winfo_children():
            w.destroy()

        kw = (keyword or "").strip().lower()
        matched = [
            f for f in self.friends
            if kw in str(f.get("nickname", "")).lower()
            or kw in str(f.get("qq_number", "")).lower()
        ]
        # 在线的排前面
        matched.sort(key=lambda f: (not f.get("online"), str(f.get("nickname", ""))))

        if not matched:
            text = "没有找到相关好友" if kw else "暂无好友，点右下角添加"
            tk.Label(self.list_frame, text=text, font=("微软雅黑", 10),
                     bg=BG, fg="#999").grid(row=0, column=0, pady=40)
            return

        online_cnt = sum(1 for f in matched if f.get("online"))
        header = tk.Frame(self.list_frame, bg="#eef1f5")
        header.grid(row=0, column=0, sticky="ew", pady=(6, 0))
        tk.Label(header, text=f"我的好友  ({online_cnt}/{len(matched)} 在线)",
                 font=("微软雅黑", 10, "bold"), bg="#eef1f5", fg="#555").pack(
            side="left", padx=8, pady=6)

        body = tk.Frame(self.list_frame, bg="white")
        body.grid(row=1, column=0, sticky="ew")
        for f in matched:
            self._add_row(body, f)

    def _add_row(self, parent, f):
        qq = str(f.get("qq_number", ""))
        nick = f.get("nickname") or qq
        online = bool(f.get("online"))

        row = tk.Frame(parent, bg="white", cursor="hand2")
        row.pack(fill="x")

        # 头像
        color = _color_for(nick) if online else "#c9cdd4"
        avatar = tk.Canvas(row, width=38, height=38, bg="white", highlightthickness=0)
        avatar.create_oval(1, 1, 37, 37, fill=color, outline=color)
        avatar.create_text(19, 19, text=nick[:1].upper(), fill="white",
                           font=("微软雅黑", 12, "bold"))
        avatar.pack(side="left", padx=(10, 8), pady=6)

        # 名字（未读时红色，闪烁就是改这个 Label 的 fg）
        lbl = tk.Label(row, text=nick, font=("微软雅黑", 11), bg="white",
                       fg="#e24b4a" if qq in self.unread else ("#333" if online else "#999"),
                       anchor="w")
        lbl.pack(side="left")
        self.labels[qq] = lbl

        tk.Label(row, text=qq, font=("微软雅黑", 9), bg="white",
                 fg="#bbb").pack(side="left", padx=(8, 0))

        tk.Label(row, text="在线" if online else "离线", font=("微软雅黑", 9),
                 bg="white", fg="#27ae60" if online else "#ccc").pack(
            side="right", padx=12)

        self._bind_all(row, lambda e, q=qq: self.open_chat(q))

    @staticmethod
    def _bind_all(widget, func):
        widget.bind("<Button-1>", func)
        for child in widget.winfo_children():
            FriendWindow._bind_all(child, func)

    def _on_wheel(self, event):
        try:
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        except tk.TclError:
            pass

    # ==================== 聊天窗 ====================
    def open_chat(self, qq):
        # 点开就把未读清掉
        self.unread.discard(qq)
        lbl = self.labels.get(qq)
        if lbl is not None:
            try:
                online = self._is_online(qq)
                lbl.config(fg="#333" if online else "#999")
            except tk.TclError:
                pass
        if not self.unread:
            self._stop_blink()

        win = self.chat_windows.get(qq)
        if win is not None:
            try:
                if win.winfo_exists():
                    win.deiconify()
                    win.lift()
                    win.focus_force()
                    return win
            except tk.TclError:
                pass

        win = ChatWindow(self.win, self.con_sk, self.usr_id, qq,
                         self.nick_map.get(qq, qq))
        self.chat_windows[qq] = win
        return win

    def _is_online(self, qq):
        for f in self.friends:
            if str(f.get("qq_number")) == str(qq):
                return bool(f.get("online"))
        return False

    # ==================== 未读闪烁 ====================
    def mark_unread(self, qq):
        self.unread.add(qq)
        if self.blink_job is None:
            self._blink()

    def _blink(self):
        if not self.unread:
            self.blink_job = None
            return
        self._blink_on = not self._blink_on
        color = "#e24b4a" if self._blink_on else "#333"
        for qq in list(self.unread):
            lbl = self.labels.get(qq)
            if lbl is None:
                continue
            try:
                lbl.config(fg=color)
            except tk.TclError:
                pass
        try:
            self.blink_job = self.win.after(500, self._blink)
        except tk.TclError:
            self.blink_job = None

    def _stop_blink(self):
        if self.blink_job is not None:
            try:
                self.win.after_cancel(self.blink_job)
            except tk.TclError:
                pass
            self.blink_job = None

    # ==================== 添加好友 ====================
    def open_add_friend(self):
        if self.search_dlg is not None:
            try:
                if self.search_dlg.win.winfo_exists():
                    self.search_dlg.win.lift()
                    self.search_dlg.win.focus_force()
                    return
            except tk.TclError:
                pass
        self.search_dlg = SearchFriend(self.win, self.con_sk, self.usr_id)

    # ==================== 收消息 ====================
    def send(self, obj):
        try:
            self.con_sk.sendall(_pack(obj))
            return True
        except OSError as e:
            self.hint.config(text=f"发送失败：{e}", fg="#a32d2d")
            return False

    def recv_loop(self):
        """子线程：只负责收包丢进队列，绝不碰控件"""
        buf = b""
        while not self._stop.is_set():
            try:
                data = self.con_sk.recv(4096)
            except OSError:
                break
            if not data:
                self.q.put({"status": "__disconnected__"})
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    self.q.put(json.loads(line.decode("utf-8")))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass

    def poll_queue(self):
        """主线程：每 80ms 取一次队列，所有界面操作都在这里做"""
        if not self._dialog_open:
            try:
                while True:
                    self.handle_msg(self.q.get_nowait())
            except queue.Empty:
                pass
        if not self._stop.is_set():
            try:
                self.win.after(80, self.poll_queue)
            except tk.TclError:
                pass

    def handle_msg(self, msg):
        st = msg.get("status")

        # ---------- 别人加你 ----------
        if st == "other_add_u":
            qq = str(msg.get("qq_number", ""))
            nick = msg.get("nickname", qq)
            self._dialog_open = True
            try:
                ok = messagebox.askokcancel(
                    "好友申请", f"{nick}（{qq}）想加你为好友，同意吗？",
                    parent=self.win)
            finally:
                self._dialog_open = False
            if ok:
                self.send({"status": "acpt_frd_request",
                           "beitongyi_qq_number": qq,
                           "tongyi_qq_number": self.usr_id})
            return

        # ---------- 你同意后，服务器推最新好友列表 ----------
        if st == "acpt_ok":
            self.set_friends(msg.get("friends", []))
            return

        # ---------- 别人同意了你的申请 ----------
        if st == "other_acpt_ur_add":
            qq = str(msg.get("tongyi_qq_number", ""))
            nick = msg.get("nickname", qq)
            self._dialog_open = True
            try:
                messagebox.showinfo("好友申请通过",
                                    f"{nick}（{qq}）已经通过了你的好友申请",
                                    parent=self.win)
            finally:
                self._dialog_open = False
            self.send({"status": "friends", "qq_number": self.usr_id})
            return

        # ---------- 搜索结果 ----------
        if st == "search_result":
            if self.search_dlg is not None:
                try:
                    if self.search_dlg.win.winfo_exists():
                        self.search_dlg.show_result(msg)
                except tk.TclError:
                    pass
            return

        if st == "add_sent":
            self.hint.config(text=f"好友申请已发送给 {msg.get('qq_number')}", fg="#3b6d11")
            return

        # ---------- 收到聊天消息 ----------
        if st == "other_chat_u":
            src = str(msg.get("src_id", ""))
            content = msg.get("chat_content", "")
            nick = msg.get("nickname", src)
            self.nick_map.setdefault(src, nick)

            win = self.chat_windows.get(src)
            shown = False
            if win is not None:
                try:
                    if win.winfo_exists():
                        win.append_incoming(src, content)
                        shown = True
                except tk.TclError:
                    pass
            if not shown:
                # 窗口没开（或已最小化）：存历史 + 标未读，名字变红闪烁
                remember(self.usr_id, src, content)
                self.mark_unread(src)
            return

        # ---------- 好友列表刷新 ----------
        if st == "friends":
            self.set_friends(msg.get("friends", []))
            return

        if st == "error":
            self._dialog_open = True
            try:
                messagebox.showwarning("提示", msg.get("msg", ""), parent=self.win)
            finally:
                self._dialog_open = False
            return

        if st == "__disconnected__":
            self.hint.config(text="与服务器断开连接", fg="#a32d2d")
            return

    def set_friends(self, friends):
        self.friends = list(friends or [])
        self.nick_map = {f["qq_number"]: f.get("nickname", f["qq_number"])
                         for f in self.friends}
        self.render(self.search_var.get())

    # ==================== 关闭 ====================
    def close(self):
        self._stop.set()
        self._stop_blink()
        try:
            self.con_sk.close()
        except OSError:
            pass
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        if self.on_close:
            self.on_close()
