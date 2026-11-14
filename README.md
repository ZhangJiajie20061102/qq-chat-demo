# Python 多线程 Socket 聊天程序

基于 Python `socket` + `threading` + `tkinter` + `sqlite3` 实现的仿 QQ 局域网聊天程序。

服务器用「账号 -> socket」映射表做消息转发，每个客户端连接开一个独立线程；客户端用 tkinter 写界面，主线程管界面、子线程管收包。

## 功能

- **注册**：账号 / 昵称 / 密码写入 sqlite，服务端二次校验（非空、密码至少 6 位、QQ 号查重）
- **登录**：账号密码校验通过后把 socket 登记进在线表，拒绝重复登录
- **好友列表**：登录后弹出仿 QQ 窗口，显示好友昵称 + QQ 号 + 在线状态（绿点/灰点）
- **添加好友**：按 QQ 号搜索 -> 发送申请 -> 对方弹窗确认 -> 双方好友列表实时更新，并写回数据库
- **聊天**：双击好友开聊天窗，消息经服务器转发；聊天窗关着时，好友列表里的名字会变红闪烁提醒
- **断线处理**：客户端断开自动清理在线表，好友列表同步更新在线状态

## 快速开始

环境要求：Python 3.8+（需带 tkinter），无需任何第三方库。

```bash
# 1. 启动服务器（会自动创建 user_data.db 并预置测试账号）
python server.py

# 2. 另开终端（或多个 PyCharm Run 窗口）启动客户端
python main.py
```

至少开两个客户端才能测试加好友和聊天。

预置账号（密码均为 `password`）：

| QQ 号 | 昵称 | 初始好友 |
|---|---|---|
| 123 | 阿三 | qq助手、456 |
| 456 | 小四 | qq助手、123 |
| 789 | 小五 | qq助手 |
| qq助手 | QQ助手 | — |

端口被占用时可用环境变量换端口，客户端与服务器要一致：

```bash
set CHAT_PORT=9100 && python server.py
```

## 文件结构

```
.
├── server.py          服务器：七个 status 分支、在线表、sqlite 读写
├── main.py            登录窗口，登录成功后把 socket 交接给好友列表
├── regi.py            注册窗口
├── friend_window.py   好友列表：收包线程、未读红闪、多聊天窗管理
├── search_friend.py   搜索并添加好友
├── chat_win.py        聊天窗口
├── test.py            多线程基础练习（两个死循环同时运行）
└── user_data.db       首次启动 server.py 时自动生成
```

## 通信协议

传输层：**一行一个 JSON，以 `\n` 结尾**。

TCP 是字节流，不存在消息边界。如果服务端连发两次 `sendall`、客户端连发两次 `recv`，两次数据很可能被合并到一次接收里，导致协议判断失败。因此统一用 `\n` 分帧，接收端维护缓冲区按行切分，粘包和半包都能正确处理。

业务层：请求与响应都是 `{status: ..., ...}`。

### 客户端 -> 服务器

| status | 用途 | 主要字段 |
|---|---|---|
| `register` | 注册 | `qq_number, nickname, password, friend_list` |
| `login` | 登录 | `qq_number, password` |
| `friends` | 拉取好友列表 | `qq_number` |
| `search_frd_exist` | 搜索好友 | `qq_number, search_dst_id` |
| `add_frd_command` | 发送好友申请 | `qq_number, search_dst_id` |
| `acpt_frd_request` | 同意好友申请 | `beitongyi_qq_number, tongyi_qq_number` |
| `start_chat` | 发送聊天消息 | `src_id, dst_id, chat_content` |

### 服务器 -> 客户端

| status | 含义 |
|---|---|
| `register_ok` / `register_fail` | 注册结果 |
| `login_ok` / `login_fail` | 登录结果（`login_ok` 附带 `friends` 列表） |
| `friends` | 好友列表，含昵称与在线状态 |
| `search_result` | 搜索结果（`found` + 昵称 / 在线状态） |
| `add_sent` | 好友申请已转发 |
| `other_add_u` | 别人加你为好友，客户端弹窗确认 |
| `acpt_ok` | 你同意后服务器返回的最新好友列表 |
| `other_acpt_ur_add` | 别人同意了你的申请，刷新好友列表 |
| `other_chat_u` | 收到别人的消息 |
| `error` | 出错提示 |

## 实现要点

**1. 每个连接一个线程**

`accept()` 本身是阻塞的，`recv()` 也是阻塞的。如果只有一个主线程，第一个客户端连进来就把主线程占死，后面的连接进不来。所以主线程只负责不停 `accept`，每接到一个连接就 `Thread(target=handle_client)` 开一个线程处理它的完整生命周期。

**2. 在线表必须加锁**

`client_ol_info` 是多个线程共享的普通 dict，不是线程安全的。所有读写都放在 `with lock:` 里，数据库写入单独用 `db_lock`，避免两个线程同时写 sqlite 报 `database is locked`。

**3. 断线清理要判断是不是自己那条连接**

```python
if client_ol_info.get(qq) is client_socket:
    del client_ol_info[qq]
```

否则同账号重新登录后，旧连接的 `finally` 会把新连接的映射删掉。

**4. tkinter 不是线程安全的**

接收线程只往 `queue.Queue` 里塞数据，界面更新统一由主线程通过 `root.after(100, poll_queue)` 轮询完成。在子线程里直接改控件会随机崩溃。

## 测试

两份测试脚本覆盖协议层与界面层，全部通过：

- **协议层 35 项**：注册查重、密码校验、重复登录拦截、搜索命中/未命中/已是好友、加好友全链路、消息转发、给离线用户发消息、粘包两条正确拆开、半包拼回完整消息、断线重登
- **界面层 41 项**：好友渲染与在线灰显、搜索过滤、未读变红、点开恢复、实时追加、关窗重开历史保留、发送包格式、添加好友完整流程、窗口关闭清理
