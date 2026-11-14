# -*- coding: utf-8 -*-
"""
协议层端到端测试

把一个干净的服务器副本拷到临时目录、用随机空闲端口启动，然后用真实 socket
把注册 / 登录 / 搜索 / 加好友 / 聊天 / 粘包 / 断线清理全部跑一遍。

全程不碰项目里的 user_data.db。

用法：
    python tests/test_protocol.py
退出码：0 全部通过，1 有失败
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ["server.py", "main.py", "regi.py", "friend_window.py",
         "search_friend.py", "chat_win.py"]


def free_port():
    """让系统分配一个空闲端口，避免和正在运行的 server.py 撞车"""
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


PORT = free_port()


def pack(obj):
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


class Client:
    def __init__(self, qq=None, pwd=None, label=""):
        self.label = label or qq or "?"
        self.s = socket.socket()
        self.s.settimeout(8)
        self.s.connect(("127.0.0.1", PORT))
        self.buf = b""
        if qq:
            self.login = self.request({"status": "login", "qq_number": qq, "password": pwd})

    def send(self, obj):
        self.s.sendall(pack(obj))

    def send_raw(self, data):
        self.s.sendall(data)

    def recv(self, timeout=8):
        self.s.settimeout(timeout)
        while b"\n" not in self.buf:
            d = self.s.recv(4096)
            if not d:
                return None
            self.buf += d
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line.decode("utf-8"))

    def request(self, obj):
        self.send(obj)
        return self.recv()

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


def main():
    # ---------- 准备干净副本 ----------
    tmp = tempfile.mkdtemp(prefix="chat_test_")
    for f in FILES:
        shutil.copy(os.path.join(BASE, f), tmp)
    print(f"[准备] 已复制 {len(FILES)} 个文件到 {tmp}")

    env = {**os.environ, "CHAT_PORT": str(PORT)}
    proc = subprocess.Popen([sys.executable, "-u", "server.py"], cwd=tmp, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    time.sleep(2.5)
    if proc.poll() is not None:
        print("[失败] 服务器没起来：")
        print(proc.stdout.read())
        return 1
    print(f"[启动] server.py 监听 {PORT}\n")

    ok = 0
    fail = 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  [OK]   {name}")
        else:
            fail += 1
            print(f"  [FAIL] {name}  {detail}")

    try:
        print("【1】注册")
        c = Client()
        r = c.request({"status": "register", "qq_number": "111111", "nickname": "alice",
                       "password": "123456", "friend_list": ["qq助手"]})
        check("新账号注册成功", r.get("status") == "register_ok", r)
        c.close()

        # 注册分支处理完就关连接，所以每次注册都开新连接
        c = Client()
        r = c.request({"status": "register", "qq_number": "111111", "nickname": "alice",
                       "password": "123456"})
        check("重复注册被拒", r.get("status") == "register_fail", r)
        c.close()

        c = Client()
        r = c.request({"status": "register", "qq_number": "222222", "nickname": "x",
                       "password": "123"})
        check("密码太短被拒", r.get("status") == "register_fail", r)
        c.close()

        print("\n【2】登录")
        c = Client()
        r = c.request({"status": "login", "qq_number": "123", "password": "wrong"})
        check("密码错被拒", r.get("status") == "login_fail", r)
        c.close()

        c = Client()
        r = c.request({"status": "login", "qq_number": "nobody", "password": "x"})
        check("账号不存在被拒", r.get("status") == "login_fail", r)
        c.close()

        a = Client("123", "password", "123")
        r = a.login
        check("123 登录成功", r.get("status") == "login_ok", r)
        check("登录返回昵称", r.get("nickname") == "阿三", r.get("nickname"))
        friends = r.get("friends", [])
        qqs = [f["qq_number"] for f in friends]
        check("好友列表来自数据库", "456" in qqs and "qq助手" in qqs, qqs)
        check("好友带在线状态字段", all("online" in f for f in friends), friends)
        check("qq助手 视为在线", any(f["qq_number"] == "qq助手" and f["online"] for f in friends), friends)

        b = Client("789", "password", "789")
        check("789 登录成功", b.login.get("status") == "login_ok", b.login)
        d = Client("456", "password", "456")
        check("456 登录成功", d.login.get("status") == "login_ok", d.login)

        dup = Client()
        r = dup.request({"status": "login", "qq_number": "123", "password": "password"})
        check("重复登录被拒", r.get("status") == "login_fail", r)
        dup.close()

        print("\n【3】搜索好友")
        r = a.request({"status": "search_frd_exist", "qq_number": "123", "search_dst_id": "789"})
        check("搜在线用户能找到", r.get("status") == "search_result" and r.get("found"), r)
        check("搜索结果带在线标记", r.get("online") is True, r)
        r = a.request({"status": "search_frd_exist", "qq_number": "123", "search_dst_id": "999999"})
        check("搜不存在的号找不到", r.get("found") is False, r)
        r = a.request({"status": "search_frd_exist", "qq_number": "123", "search_dst_id": "456"})
        check("已是好友的提示", r.get("found") is False and "已经是" in r.get("reason", ""), r)

        print("\n【4】添加好友")
        a.send({"status": "add_frd_command", "qq_number": "123", "search_dst_id": "789"})
        r_a = a.recv()
        r_b = b.recv()
        check("申请方收到 add_sent", r_a.get("status") == "add_sent", r_a)
        check("被申请方收到 other_add_u", r_b.get("status") == "other_add_u", r_b)
        check("other_add_u 带申请方 QQ", r_b.get("qq_number") == "123", r_b)

        b.send({"status": "acpt_frd_request", "beitongyi_qq_number": "123",
                "tongyi_qq_number": "789"})
        r_b2 = b.recv()
        r_a2 = a.recv()
        check("同意方收到 acpt_ok + 新列表", r_b2.get("status") == "acpt_ok"
              and "123" in [f["qq_number"] for f in r_b2.get("friends", [])], r_b2)
        check("申请方收到 other_acpt_ur_add", r_a2.get("status") == "other_acpt_ur_add", r_a2)

        a.send({"status": "friends", "qq_number": "123"})
        r = a.recv()
        check("123 好友列表已含 789", "789" in [f["qq_number"] for f in r.get("friends", [])], r)

        print("\n【5】聊天互发")
        a.send({"status": "start_chat", "src_id": "123", "dst_id": "789",
                "chat_content": "在吗？我是阿三"})
        r = b.recv()
        check("789 收到 other_chat_u", r.get("status") == "other_chat_u", r)
        check("消息内容正确", r.get("chat_content") == "在吗？我是阿三", r)
        check("消息带发送方 QQ", r.get("src_id") == "123", r)

        b.send({"status": "start_chat", "src_id": "789", "dst_id": "123",
                "chat_content": "在，什么事"})
        r = a.recv()
        check("123 收到回信", r.get("chat_content") == "在，什么事", r)

        d.send({"status": "start_chat", "src_id": "456", "dst_id": "123",
                "chat_content": "我也给你发一条（未读场景）"})
        r = a.recv()
        check("第三方也能给 123 发消息", r.get("src_id") == "456", r)

        print("\n【6】粘包 / 半包")
        # 两条 JSON 粘在一个 sendall 里
        a.send_raw(pack({"status": "search_frd_exist", "qq_number": "123",
                         "search_dst_id": "789"})
                   + pack({"status": "friends", "qq_number": "123"}))
        r1 = a.recv()
        r2 = a.recv()
        check("粘包两条被正确拆开(1)", r1.get("status") == "search_result", r1)
        check("粘包两条被正确拆开(2)", r2.get("status") == "friends", r2)

        # 半包：把一条消息拆成两段发
        data = pack({"status": "friends", "qq_number": "123"})
        a.send_raw(data[:7])
        time.sleep(0.2)
        a.send_raw(data[7:])
        r = a.recv()
        check("半包也能拼回完整消息", r.get("status") == "friends", r)

        print("\n【7】异常与清理")
        r = a.request({"status": "bogus_status"})
        check("未知 status 回 error", r.get("status") == "error", r)

        b.close()
        time.sleep(0.6)
        a.send({"status": "start_chat", "src_id": "123", "dst_id": "789",
                "chat_content": "现在你应该离线了"})
        r = a.recv()
        check("给离线用户发消息回 error", r.get("status") == "error", r)

        e = Client("789", "password", "789")
        check("断线后 789 能重新登录", e.login.get("status") == "login_ok", e.login)
        e.close()

        # 注册完就能登录（验收闭环）
        f = Client("111111", "123456", "111111")
        check("新注册账号能登录", f.login.get("status") == "login_ok", f.login)
        f.close()

    finally:
        for x in ("a", "b", "d"):
            obj = locals().get(x)
            if obj is not None:
                obj.close()
        time.sleep(0.4)
        proc.terminate()
        try:
            log = proc.stdout.read()
        except Exception:
            log = ""
        print("\n" + "=" * 56)
        print(f"结果：{ok} 项通过，{fail} 项失败")
        print("=" * 56)
        print("\n--- server 日志 ---")
        print(log.strip()[-2500:])

        if fail == 0:
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print(f"\n[保留] 失败现场在 {tmp}")

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
