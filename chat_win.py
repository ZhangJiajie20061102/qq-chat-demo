# -*- coding: utf-8 -*-
"""
chat_win.py —— 仿 QQ 聊天窗口（笔记 05）

界面沿用笔记里 AI 生成的那一版（气泡 + 头像 + 时间分隔 + Enter 发送），
只改了必须改的地方：

1. 发送协议改成服务器认识的 start_chat：
       {status:"start_chat", src_id, dst_id, chat_content} + "\\n"
   笔记的 _encode_message 用的是 {type:"chat", from, to, content}，跟服务器对不上。
2. 删掉笔记里的 self.root.update() —— ChatWindow 继承的是 Toplevel，没有 .root 属性，
   这一行必抛 AttributeError，而它被外层 except 吞掉，表现就是"消息到了但不显示"。
3. 历史记录仍放模块级 _HISTORY，所以关掉窗口再打开，聊天记录还在。
"""

import json
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

# {(我方QQ, 对方QQ): [{"sender": xx, "content": xx, "ts": 时间戳}, ...]}
_HISTORY = {}
_LOCK = threading.RLock()


def _key(usr_id, peer_id):
    return (str(usr_id), str(peer_id))


def get_history(usr_id, peer_id):
    with _LOCK:
        return list(_HISTORY.get(_key(usr_id, peer_id), []))


def clear_history(usr_id=None, peer_id=None):
    with _LOCK:
        if usr_id is None and peer_id is None:
            _HISTORY.clear()
        else:
            _HISTORY.pop(_key(usr_id, peer_id), None)


def remember(usr_id, sender_id, content, ts=None):
    """只存历史不渲染（窗口没打开时用），下次打开窗口会自动显示"""
    rec = {"sender": str(sender_id), "content": content, "ts": ts or time.time()}
    with _LOCK:
        _HISTORY.setdefault(_key(usr_id, sender_id), []).append(rec)
    return rec


class ChatWindow(tk.Toplevel):
    """与某位好友的单聊窗口"""

    BG = "#EDEDED"
    HEADER_BG = "#1296DB"
    MY_BUBBLE = "#95EC69"
    OTHER_BUBBLE = "#FFFFFF"
    INPUT_BG = "#F7F7F7"

    def __init__(self, parent, client_sk, usr_id, peer_id, peer_nick="", chat_content=None):
        super().__init__(parent)

        self.client_sk = client_sk
        self.usr_id = str(usr_id)
        self.peer_id = str(peer_id)
        self.peer_nick = peer_nick or str(peer_id)

        self._bubbles = []
        self._wrap_len = 300
        self._last_ts = None

        self.title(f"与 {self.peer_nick} 聊天中")
        self.geometry("720x620")
        self.minsize(520, 430)
        self.configure(bg=self.BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_header()
        self._build_input()      # 先 pack 底部，再 pack 主体
        self._build_body()
        self._bind_events()

        self._load_history()
        self.after(120, lambda: self.input_text.focus_set())

    # ================= 界面 =================
    def _build_header(self):
        header = tk.Frame(self, bg=self.HEADER_BG, height=64)
        header.pack(side="top", fill="x")
        header.pack_propagate(False)

        av = tk.Canvas(header, width=40, height=40, bg=self.HEADER_BG,
                       highlightthickness=0)
        av.pack(side="left", padx=(16, 10), pady=12)
        self._draw_avatar(av, self.peer_nick, "#FFFFFF", self.HEADER_BG, 40)

        info = tk.Frame(header, bg=self.HEADER_BG)
        info.pack(side="left", pady=12)
        tk.Label(info, text=self.peer_nick, bg=self.HEADER_BG, fg="white",
                 font=("微软雅黑", 12, "bold")).pack(anchor="w")
        tk.Label(info, text=f"QQ {self.peer_id}", bg=self.HEADER_BG, fg="#D9F0FF",
                 font=("微软雅黑", 8)).pack(anchor="w")

    def _build_body(self):
        body = tk.Frame(self, bg=self.BG)
        body.pack(side="top", fill="both", expand=True)

        self.canvas = tk.Canvas(body, bg=self.BG, highlightthickness=0, bd=0)
        self.vbar = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)

        self.vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.msg_frame = tk.Frame(self.canvas, bg=self.BG)
        self._win_id = self.canvas.create_window((0, 0), window=self.msg_frame,
                                                 anchor="nw")
        self.msg_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _build_input(self):
        bottom = tk.Frame(self, bg=self.INPUT_BG, height=175)
        bottom.pack(side="bottom", fill="x")
        bottom.pack_propagate(False)

        tk.Frame(bottom, bg="#DDDDDD", height=1).pack(side="top", fill="x")

        btn_bar = tk.Frame(bottom, bg=self.INPUT_BG)
        btn_bar.pack(side="bottom", fill="x", padx=12, pady=(0, 10))
        tk.Label(btn_bar, text="Enter 发送 / Shift+Enter 换行", bg=self.INPUT_BG,
                 fg="#999999", font=("微软雅黑", 8)).pack(side="left")
        self.send_btn = tk.Button(btn_bar, text="发送(S)", width=10,
                                  bg=self.HEADER_BG, fg="white", bd=0,
                                  activebackground="#0F7FBC",
                                  activeforeground="white",
                                  font=("微软雅黑", 10, "bold"), cursor="hand2",
                                  command=self.send_message)
        self.send_btn.pack(side="right")

        text_wrap = tk.Frame(bottom, bg=self.INPUT_BG)
        text_wrap.pack(side="top", fill="both", expand=True, padx=12, pady=6)

        self.input_text = tk.Text(text_wrap, height=4, wrap="word",
                                  font=("微软雅黑", 10), relief="flat", bd=0,
                                  bg="white", fg="#222222", undo=True,
                                  padx=10, pady=8, insertbackground=self.HEADER_BG)
        input_vbar = ttk.Scrollbar(text_wrap, orient="vertical",
                                   command=self.input_text.yview)
        self.input_text.configure(yscrollcommand=input_vbar.set)
        input_vbar.pack(side="right", fill="y")
        self.input_text.pack(side="left", fill="both", expand=True)

    def _bind_events(self):
        self.input_text.bind("<Return>", self._on_return)
        self.bind("<MouseWheel>", self._on_mousewheel)
        self.bind("<Button-4>", self._on_mousewheel_linux)
        self.bind("<Button-5>", self._on_mousewheel_linux)

    # ================= 事件 =================
    def _on_return(self, event):
        if event.state & 0x0001:        # 按住 Shift -> 换行
            return None
        self.send_message()
        return "break"

    def _on_mousewheel(self, event):
        if event.widget is self.input_text:
            return
        try:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
        except tk.TclError:
            pass

    def _on_mousewheel_linux(self, event):
        if event.widget is self.input_text:
            return
        try:
            self.canvas.yview_scroll(-1 if event.num == 4 else 1, "units")
        except tk.TclError:
            pass

    def _on_frame_configure(self, event=None):
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        except tk.TclError:
            pass

    def _on_canvas_configure(self, event):
        try:
            self.canvas.itemconfigure(self._win_id, width=event.width)
        except tk.TclError:
            return
        wrap = max(int(event.width * 0.62), 120)
        if wrap != self._wrap_len:
            self._wrap_len = wrap
            for lbl in self._bubbles:
                try:
                    lbl.configure(wraplength=wrap)
                except tk.TclError:
                    pass

    # ================= 发送 =================
    def send_message(self, event=None):
        text = self.input_text.get("1.0", "end-1c").strip()
        if not text:
            return "break"
        self.input_text.delete("1.0", "end")

        # 1) 自己这边先显示
        self._append_message(self.usr_id, text)

        # 2) 打包成服务器认识的格式发出去
        payload = {
            "status": "start_chat",
            "src_id": self.usr_id,
            "dst_id": self.peer_id,
            "chat_content": text,
        }
        try:
            self.client_sk.sendall(
                (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        except OSError as e:
            messagebox.showerror("发送失败", f"与服务器断开连接：{e}", parent=self)
        return "break"

    # ================= 接收 =================
    def append_incoming(self, sender_id, content, ts=None):
        """收到对方消息时由好友列表调用（已在主线程）"""
        try:
            if not self.winfo_exists():
                return
            self._append_message(sender_id, content, ts)
            self.deiconify()
            self.lift()
        except tk.TclError:
            pass

    # ================= 渲染 =================
    def _append_message(self, sender, content, ts=None):
        sender = str(sender)
        ts = ts or time.time()
        with _LOCK:
            _HISTORY.setdefault(_key(self.usr_id, self.peer_id), []).append(
                {"sender": sender, "content": content, "ts": ts})
        self._render_message(sender, content, ts)

    def _render_message(self, sender, content, ts=None, scroll=True):
        sender = str(sender)
        is_me = (sender == self.usr_id)

        ts = ts or time.time()
        if self._last_ts is None or (ts - self._last_ts) > 180:
            self._add_time_label(ts)
        self._last_ts = ts

        row = tk.Frame(self.msg_frame, bg=self.BG)
        row.pack(fill="x", padx=12, pady=4)

        av = tk.Canvas(row, width=36, height=36, bg=self.BG, highlightthickness=0)
        self._draw_avatar(av, self.usr_id if is_me else self.peer_nick,
                          "#F5A623" if is_me else "#4A90D9", "#FFFFFF", 36)
        if is_me:
            av.pack(side="right", padx=(8, 0), anchor="n")
        else:
            av.pack(side="left", padx=(0, 8), anchor="n")

        bubble = tk.Label(
            row, text=content,
            font=("微软雅黑", 10),
            bg=self.MY_BUBBLE if is_me else self.OTHER_BUBBLE,
            fg="#111111",
            justify="left",
            wraplength=self._wrap_len,
            padx=12, pady=8,
            bd=0, relief="flat",
        )
        bubble.pack(side="right" if is_me else "left", anchor="n")

        self._bubbles.append(bubble)
        if scroll:
            self._scroll_to_bottom()

    def _add_time_label(self, ts):
        txt = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
        tk.Label(self.msg_frame, text=txt, bg=self.BG, fg="#999999",
                 font=("微软雅黑", 8)).pack(pady=(10, 2))

    @staticmethod
    def _draw_avatar(canvas, text, bg_color, fg_color="#FFFFFF", size=36):
        canvas.delete("all")
        canvas.create_oval(1, 1, size - 1, size - 1, fill=bg_color, outline="")
        short = (text or "?")[-2:]
        canvas.create_text(size / 2, size / 2, text=short, fill=fg_color,
                           font=("微软雅黑", max(8, size // 4), "bold"))

    def _load_history(self):
        for rec in get_history(self.usr_id, self.peer_id):
            self._render_message(rec["sender"], rec["content"],
                                 rec.get("ts"), scroll=False)
        self._scroll_to_bottom()

    # ================= 工具 =================
    def _scroll_to_bottom(self):
        try:
            self.canvas.update_idletasks()
            self.canvas.yview_moveto(1.0)
        except tk.TclError:
            pass

    def _on_close(self):
        try:
            self.destroy()
        except tk.TclError:
            pass


# ==================== 单独运行本文件可以预览界面 ====================
if __name__ == "__main__":
    class FakeSocket:
        def sendall(self, data):
            print("[已发送] " + data.decode("utf-8").strip())

    root = tk.Tk()
    root.title("QQ 主面板")
    root.geometry("320x220")
    root.configure(bg="#F0F0F0")
    tk.Label(root, text="聊天窗口预览", font=("微软雅黑", 13, "bold"),
             bg="#F0F0F0").pack(pady=14)

    fake = FakeSocket()
    MY_QQ, PEER = "10001", "10002"

    win_holder = {}

    def open_win():
        win_holder["w"] = ChatWindow(root, fake, MY_QQ, PEER, "小四")

    tk.Button(root, text="打开与 10002 的聊天窗口", font=("微软雅黑", 10),
              bg="#1296DB", fg="white", bd=0, width=24, height=2,
              cursor="hand2", command=open_win).pack(pady=8)

    def fake_recv():
        if "w" in win_holder and win_holder["w"].winfo_exists():
            win_holder["w"].append_incoming(PEER, "在吗？我这边测试一下自动刷新～")

    root.after(2500, fake_recv)
    root.mainloop()
