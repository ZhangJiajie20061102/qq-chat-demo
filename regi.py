"""
聊天程序 02 —— 注册界面

笔记的思路：在注册按钮的 register() 里把文本框内容取出来，做成 01 笔记里的
status + information 形式，打包发给服务器，服务器查重后写进 sqlite。

和笔记原版的两处不同（原版有 bug）：
1. 先做表单校验，全部通过才发请求。原版是"先发后校验"，空表单也会发出去。
2. messagebox.showerror 必须传两个参数（标题 + 内容），原版只传了一个，会 TypeError。
"""
import json
import os
import socket
import tkinter as tk
from tkinter import messagebox

SERVER_HOST = os.environ.get("CHAT_HOST", "127.0.0.1")
SERVER_PORT = int(os.environ.get("CHAT_PORT", "8999"))
SERVER = (SERVER_HOST, SERVER_PORT)


class RegisterWindow:
    """简洁的注册窗体"""

    def __init__(self, parent):
        self.parent = parent
        self.win = tk.Toplevel(parent)
        self.win.title("注册账号")
        self.win.resizable(False, False)
        self.win.configure(bg="#f5f6fa")
        self.win.transient(parent)
        self.win.grab_set()          # 模态窗口
        self.center(400, 540)
        self.build_ui()

    def center(self, w, h):
        self.win.update_idletasks()
        x = self.parent.winfo_rootx() + (self.parent.winfo_width() - w) // 2
        y = self.parent.winfo_rooty() + (self.parent.winfo_height() - h) // 2
        self.win.geometry(f"{w}x{h}+{x}+{y}")

    def build_ui(self):
        # ---------- 顶部 ----------
        top = tk.Frame(self.win, bg="#12b7f5", height=90)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Label(top, text="注册新账号", font=("微软雅黑", 16, "bold"),
                 fg="white", bg="#12b7f5").pack(pady=30)

        # ---------- 表单 ----------
        form = tk.Frame(self.win, bg="#f5f6fa")
        form.pack(fill="both", expand=True, padx=40, pady=20)

        self.entry_user = self._field(form, "账号")
        self.entry_nick = self._field(form, "昵称")
        self.entry_pwd = self._field(form, "密码（至少 6 位）", show="*")
        self.entry_pwd2 = self._field(form, "确认密码", show="*")

        tk.Button(form, text="注 册", font=("微软雅黑", 12, "bold"),
                  bg="#12b7f5", fg="white",
                  activebackground="#0aa5e0", activeforeground="white",
                  relief="flat", cursor="hand2",
                  command=self.register).pack(fill="x", ipady=7, pady=(6, 8))

        tk.Button(form, text="取消", font=("微软雅黑", 10),
                  bg="#f5f6fa", fg="#888", bd=0,
                  activebackground="#f5f6fa", activeforeground="#555",
                  cursor="hand2",
                  command=self.win.destroy).pack()

    def _field(self, parent, label, show=""):
        tk.Label(parent, text=label, font=("微软雅黑", 10),
                 bg="#f5f6fa", fg="#666").pack(anchor="w")
        entry = tk.Entry(parent, font=("微软雅黑", 11), relief="flat",
                         bg="white", show=show, highlightthickness=1,
                         highlightbackground="#dcdde1",
                         highlightcolor="#12b7f5")
        entry.pack(fill="x", ipady=7, pady=(5, 12))
        return entry

    # ---------- 事件 ----------
    def register(self):
        user = self.entry_user.get().strip()
        nick = self.entry_nick.get().strip()
        pwd = self.entry_pwd.get().strip()
        pwd2 = self.entry_pwd2.get().strip()

        # ---- 第一步：本地校验（放在发送之前！）----
        if not user or not nick or not pwd or not pwd2:
            messagebox.showwarning("提示", "请填写完整信息", parent=self.win)
            return
        if len(pwd) < 6:
            messagebox.showwarning("提示", "密码至少 6 位", parent=self.win)
            return
        if pwd != pwd2:
            messagebox.showwarning("提示", "两次输入的密码不一致", parent=self.win)
            return

        # ---- 第二步：打包成 status + information ----
        usr_regi_info = {}
        usr_regi_info["nickname"] = nick
        usr_regi_info["qq_number"] = user
        usr_regi_info["password"] = pwd
        usr_regi_info["friend_list"] = ["qq助手", ]
        usr_regi_info["status"] = "register"

        # ---- 第三步：发给服务器，等它告诉我们这个号能不能注册 ----
        try:
            sk = socket.socket()
            sk.settimeout(5)
            sk.connect(SERVER)
            sk.sendall((json.dumps(usr_regi_info, ensure_ascii=False) + "\n").encode("utf-8"))

            buf = b""
            while b"\n" not in buf:
                data = sk.recv(4096)
                if not data:
                    break
                buf += data
            sk.close()
            reply = json.loads(buf.split(b"\n")[0].decode("utf-8"))
        except (OSError, IndexError, json.JSONDecodeError) as e:
            messagebox.showerror("连接失败",
                                 f"连不上服务器，请先运行 server.py\n\n{e}",
                                 parent=self.win)
            return

        # ---- 第四步：按服务器返回的 status 给提示 ----
        if reply.get("status") == "register_ok":
            messagebox.showinfo(
                "注册成功",
                f"恭喜您，已经注册成功了！\n账号：{user}\n昵称：{nick}\n\n现在可以返回登录界面登录",
                parent=self.win,
            )
            self.win.destroy()
        else:
            messagebox.showerror("注册失败",
                                 reply.get("reason", "未知错误"),
                                 parent=self.win)


# 单独运行这个文件也能测试注册窗口
if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("400x480")
    RegisterWindow(root)
    root.mainloop()
