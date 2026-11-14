# -*- coding: utf-8 -*-
"""
server.py —— 多线程 socket 聊天服务器（笔记 01~05 合并最终版）

传输层：一行一个 JSON，用 "\\n" 结尾（解决 TCP 粘包，笔记原版靠两次 recv 是偶发失败的）
业务层：请求 {status: ..., ...}   响应 {status: ..., ...}

status 一览
    客户端 -> 服务器
        register          注册        {qq_number, nickname, password, friend_list}
        login             登录        {qq_number, password}
        friends           拉好友列表  {qq_number}
        search_frd_exist  搜索好友    {qq_number, search_dst_id}
        add_frd_command   发好友申请  {qq_number, search_dst_id}
        acpt_frd_request  同意申请    {beitongyi_qq_number, tongyi_qq_number}
        start_chat        发聊天消息  {src_id, dst_id, chat_content}
    服务器 -> 客户端
        register_ok / register_fail
        login_ok / login_fail
        friends           好友列表
        search_result     搜索结果
        add_sent          申请已转发
        other_add_u       别人加你为好友（请弹窗确认）
        acpt_ok           你同意后服务器给的最新好友列表
        other_acpt_ur_add 别人同意了你的申请
        other_chat_u      别人给你发消息
        error             出错提示
"""

import json
import os
import socket
import sqlite3
import sys
import threading

# Windows 控制台是 GBK，直接 print 中文可能 UnicodeEncodeError，这里兜一下
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HOST = "0.0.0.0"
PORT = int(os.environ.get("CHAT_PORT", "8999"))
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_data.db")

SYSTEM_FRIEND = "qq助手"        # 预置的"系统好友"，界面上永远显示在线

client_ol_info = {}             # {QQ号: socket}   在线表 = 笔记里说的"账号 -> socket 映射"
lock = threading.Lock()         # 保护在线表
db_lock = threading.Lock()      # 保护数据库写入


# ==================== 数据库 ====================

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nickname TEXT NOT NULL,
            qq_number TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            friend_list TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    return conn


def init_db():
    """建表 + 预置几个能直接登录的测试账号"""
    preset = [
        ("阿三", "123", "password", [SYSTEM_FRIEND, "456"]),
        ("小四", "456", "password", [SYSTEM_FRIEND, "123"]),
        ("小五", "789", "password", [SYSTEM_FRIEND]),
        ("QQ助手", SYSTEM_FRIEND, "password", []),
    ]
    conn = get_conn()
    try:
        for nick, qq, pwd, fl in preset:
            conn.execute(
                "INSERT OR IGNORE INTO users (nickname, qq_number, password, friend_list)"
                " VALUES (?, ?, ?, ?)",
                (nick, qq, pwd, json.dumps(fl, ensure_ascii=False)),
            )
        conn.commit()
    finally:
        conn.close()


def check_qq_number_exists(qq_number):
    conn = get_conn()
    try:
        row = conn.execute("SELECT COUNT(*) FROM users WHERE qq_number = ?",
                           (qq_number,)).fetchone()
        return row[0] > 0
    finally:
        conn.close()


def store_user_data(data):
    """注册写库。返回 (成功?, 失败原因)"""
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO users (nickname, qq_number, password, friend_list)"
            " VALUES (?, ?, ?, ?)",
            (data["nickname"], data["qq_number"], data["password"],
             json.dumps(data.get("friend_list") or [SYSTEM_FRIEND], ensure_ascii=False)),
        )
        conn.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, "QQ号已存在"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


def qq_and_pwd_correct(qq_number, qq_pwd):
    """校验账号密码。成功返回 (昵称, None)，失败返回 (None, 原因)"""
    conn = get_conn()
    try:
        row = conn.execute("SELECT nickname, password FROM users WHERE qq_number = ?",
                           (qq_number,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None, "账号不存在，请先注册"
    if row[1] != qq_pwd:
        return None, "密码错误"
    return row[0], None


def get_nickname(qq_number):
    conn = get_conn()
    try:
        row = conn.execute("SELECT nickname FROM users WHERE qq_number = ?",
                           (qq_number,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else qq_number


def get_friend_list(qq_number):
    conn = get_conn()
    try:
        row = conn.execute("SELECT friend_list FROM users WHERE qq_number = ?",
                           (qq_number,)).fetchone()
    finally:
        conn.close()
    if not row or not row[0]:
        return []
    try:
        lst = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return []
    return lst if isinstance(lst, list) else []


def save_friend_list(qq_number, lst):
    conn = get_conn()
    try:
        conn.execute("UPDATE users SET friend_list = ? WHERE qq_number = ?",
                     (json.dumps(lst, ensure_ascii=False), qq_number))
        conn.commit()
    finally:
        conn.close()


def add_friend_pair(a, b):
    """双向写库：a 加 b 的同时 b 也加 a（笔记里只改了内存，重启就没了）"""
    with db_lock:
        for me, other in ((a, b), (b, a)):
            lst = get_friend_list(me)
            if other not in lst:
                lst.append(other)
                save_friend_list(me, lst)


def build_friend_payload(qq_number):
    """把好友列表拼成界面能直接渲染的结构 [{qq_number, nickname, online}]"""
    with lock:
        online_set = set(client_ol_info)
    out = []
    for f in get_friend_list(qq_number):
        out.append({
            "qq_number": f,
            "nickname": get_nickname(f),
            "online": (f in online_set) or (f == SYSTEM_FRIEND),
        })
    return out


# ==================== socket 收发 ====================

def send_json(sock, obj):
    """发一行 JSON。返回 False 表示对端已断开"""
    try:
        sock.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        return True
    except OSError:
        return False


def recv_messages(sock, buf):
    """
    读一批数据并按 \\n 切包。
    返回 (消息列表, 新缓冲)；消息列表为 None 表示对端关闭。
    —— 这就是笔记原版缺的东西：两次 recv 猜边界，粘包就全乱。
    """
    data = sock.recv(4096)
    if not data:
        return None, buf
    buf += data
    msgs = []
    while b"\n" in buf:
        line, buf = buf.split(b"\n", 1)
        line = line.strip()
        if not line:
            continue
        try:
            msgs.append(json.loads(line.decode("utf-8")))
        except (json.JSONDecodeError, UnicodeDecodeError):
            print(f"[警告] 收到无法解析的数据: {line[:60]!r}")
    return msgs, buf


# ==================== 业务分支 ====================

def handle_register(sock, msg):
    qq = str(msg.get("qq_number", "")).strip()
    nick = str(msg.get("nickname", "")).strip()
    pwd = str(msg.get("password", ""))

    if not qq or not nick or not pwd:
        send_json(sock, {"status": "register_fail", "reason": "账号、昵称、密码都不能为空"})
        return
    if len(pwd) < 6:
        send_json(sock, {"status": "register_fail", "reason": "密码至少 6 位"})
        return
    if check_qq_number_exists(qq):
        send_json(sock, {"status": "register_fail", "reason": f"QQ号 {qq} 已存在，请重新输入"})
        print(f"[注册失败] {qq} 已存在")
        return

    ok, err = store_user_data({
        "nickname": nick, "qq_number": qq, "password": pwd,
        "friend_list": msg.get("friend_list") or [SYSTEM_FRIEND],
    })
    if not ok:
        send_json(sock, {"status": "register_fail", "reason": err or "写入数据库失败"})
        print(f"[注册失败] {qq}: {err}")
        return

    send_json(sock, {"status": "register_ok", "qq_number": qq, "nickname": nick})
    print(f"[注册] {qq}({nick}) 注册成功")


def dispatch(sock, me, msg):
    """登录之后的各种业务消息"""
    status = msg.get("status")

    # ---------- 拉好友列表 ----------
    if status == "friends":
        send_json(sock, {"status": "friends", "friends": build_friend_payload(me)})
        return

    # ---------- 搜索好友 ----------
    if status == "search_frd_exist":
        target = str(msg.get("search_dst_id", "")).strip()
        if not target:
            send_json(sock, {"status": "search_result", "found": False,
                             "qq_number": target, "reason": "请输入要查找的 QQ 号"})
            return
        if target == me:
            send_json(sock, {"status": "search_result", "found": False,
                             "qq_number": target, "reason": "不能添加自己"})
            return
        if target in get_friend_list(me):
            send_json(sock, {"status": "search_result", "found": False,
                             "qq_number": target, "reason": f"{target} 已经是你的好友了"})
            return
        if not check_qq_number_exists(target):
            send_json(sock, {"status": "search_result", "found": False,
                             "qq_number": target, "reason": f"没有 {target} 这个账号"})
            print(f"[搜索] {me} 查 {target}: 不存在")
            return
        with lock:
            online = target in client_ol_info
        send_json(sock, {"status": "search_result", "found": True,
                         "qq_number": target, "nickname": get_nickname(target),
                         "online": online, "reason": ""})
        print(f"[搜索] {me} 查 {target}: 存在，{'在线' if online else '离线'}")
        return

    # ---------- A 申请加 B 为好友：转发给 B ----------
    if status == "add_frd_command":
        target = str(msg.get("search_dst_id", "")).strip()
        with lock:
            target_sock = client_ol_info.get(target)
        if target_sock is None:
            send_json(sock, {"status": "error",
                             "msg": f"{target} 不在线，好友申请发不出去"})
            return
        if target in get_friend_list(me):
            send_json(sock, {"status": "error", "msg": f"{target} 已经是你的好友了"})
            return
        send_json(target_sock, {"status": "other_add_u", "qq_number": me,
                                "nickname": get_nickname(me)})
        send_json(sock, {"status": "add_sent", "qq_number": target})
        print(f"[好友申请] {me} -> {target}")
        return

    # ---------- B 同意：双向写库，并通知 A ----------
    if status == "acpt_frd_request":
        requester = str(msg.get("beitongyi_qq_number", "")).strip()
        if not requester or not check_qq_number_exists(requester):
            send_json(sock, {"status": "error", "msg": "对方账号不存在，同意失败"})
            return
        add_friend_pair(requester, me)
        send_json(sock, {"status": "acpt_ok", "friends": build_friend_payload(me)})
        with lock:
            requester_sock = client_ol_info.get(requester)
        if requester_sock is not None:
            send_json(requester_sock, {
                "status": "other_acpt_ur_add",
                "tongyi_qq_number": me,
                "nickname": get_nickname(me),
            })
        print(f"[加好友成功] {me} 同意了 {requester} 的申请")
        return

    # ---------- 聊天消息转发 ----------
    if status == "start_chat":
        dst = str(msg.get("dst_id", "")).strip()
        content = msg.get("chat_content", "")
        with lock:
            dst_sock = client_ol_info.get(dst)
        if dst_sock is None:
            send_json(sock, {"status": "error", "msg": f"{dst} 不在线，消息没发出去"})
            return
        send_json(dst_sock, {"status": "other_chat_u", "src_id": me,
                             "nickname": get_nickname(me), "chat_content": content})
        return

    send_json(sock, {"status": "error", "msg": f"未知的 status: {status}"})


# ==================== 每个客户端一个线程 ====================

def handle_client(client_socket, addr):
    qq = None
    buf = b""
    pending = []

    def next_msg():
        """取一条完整消息；None 表示连接断了"""
        nonlocal buf
        if pending:
            return pending.pop(0)
        while True:
            msgs, buf = recv_messages(client_socket, buf)
            if msgs is None:
                return None
            if msgs:
                pending.extend(msgs)
                return pending.pop(0)

    try:
        first = next_msg()
        if first is None:
            return

        status = first.get("status")

        # ---------- 注册：写完就关连接，不进在线表 ----------
        if status == "register":
            handle_register(client_socket, first)
            return

        # ---------- 登录 ----------
        if status != "login":
            send_json(client_socket, {"status": "error",
                                      "msg": "第一个包必须是 register 或 login"})
            return

        qq = str(first.get("qq_number", "")).strip()
        pwd = first.get("password", "")
        if not qq:
            send_json(client_socket, {"status": "login_fail", "reason": "QQ号不能为空"})
            return

        nickname, err = qq_and_pwd_correct(qq, pwd)
        if err:
            send_json(client_socket, {"status": "login_fail", "reason": err})
            print(f"[拒绝登录] {qq}: {err} {addr}")
            return

        # 认证通过才登记在线表（顺序不能反，否则谁都能顶别人的号）
        with lock:
            if qq in client_ol_info:
                send_json(client_socket, {"status": "login_fail",
                                          "reason": f"{qq} 已经在线了，不能重复登录"})
                return
            client_ol_info[qq] = client_socket
            online_now = sorted(client_ol_info)

        send_json(client_socket, {
            "status": "login_ok",
            "qq_number": qq,
            "nickname": nickname,
            "friends": build_friend_payload(qq),
        })
        print(f"[上线] {qq}({nickname}) {addr}，当前在线 {online_now}")

        # ---------- 登录后：循环收各种业务消息 ----------
        while True:
            msg = next_msg()
            if msg is None:
                break
            dispatch(client_socket, qq, msg)

    except (ConnectionResetError, OSError) as e:
        print(f"[异常断开] {qq or addr}: {e}")
    except Exception as e:
        print(f"[处理出错] {qq or addr}: {type(e).__name__}: {e}")
    finally:
        # 断线清理：只删自己那条映射，防止误删别人的新连接
        if qq:
            removed = False
            with lock:
                if client_ol_info.get(qq) is client_socket:
                    del client_ol_info[qq]
                    removed = True
                online_now = sorted(client_ol_info)
            if removed:
                print(f"[下线] {qq}，当前在线 {online_now}")
        try:
            client_socket.close()
        except OSError:
            pass


def main():
    init_db()
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # 重启不报端口占用
    try:
        srv.bind((HOST, PORT))
    except OSError as e:
        print(f"[启动失败] 端口 {PORT} 绑不上：{e}")
        print("  可能是上一次的 server 还没关，或者端口被别的程序占了。")
        print("  换个端口：set CHAT_PORT=9100 && python server.py")
        return
    srv.listen(100)
    print(f"服务器已启动 {HOST}:{PORT}")
    print(f"数据库：{DB_PATH}")
    print("预置账号：123 / 456 / 789 / qq助手，密码都是 password")
    print("按 Ctrl+C 停止\n")

    try:
        while True:
            client_socket, addr = srv.accept()
            threading.Thread(target=handle_client, args=(client_socket, addr),
                             daemon=True).start()
    except KeyboardInterrupt:
        print("\n服务器已停止")
    finally:
        srv.close()


if __name__ == "__main__":
    main()
