# 分布式航班信息系统

## 已实现的服务

1. 根据出发地和目的地查询航班编号。
2. 根据航班编号查询起飞时间、票价和剩余座位数。
3. 预订座位并更新服务端的座位余量。
4. 在指定时间段内，通过 UDP 回调监控座位余量的变化。
5. 将票价设置为指定值（额外的**幂等**操作）。
6. 为航班增加座位（额外的**非幂等**操作）。

服务端可以同时保存多个客户端的监控注册。按照项目要求，客户端在监控期间保持
阻塞状态，不接受新的用户请求。

## 环境要求

- 服务端：支持 C++17 的编译器，以及 `make`。
- 客户端：Python 3.10 或更高版本。
- 不需要任何第三方 C++ 或 Python 库。

macOS 如果没有 C++ 编译器，可以先安装 Command Line Tools：

```bash
xcode-select --install
```

## 编译 C++ 服务端

在项目目录执行：

```bash
make
```

该命令会将 `src/server.cpp` 编译为可执行文件 `flight_server`。项目采用的等价编译命令为：

```bash
c++ -std=c++17 -O2 -Wall -Wextra -Wpedantic src/server.cpp -o flight_server
```

## 本机运行

先启动编译好的 C++ 服务端：

```bash
./flight_server --host 0.0.0.0 --port 8888 --semantics at-most-once
```

随后启动一个或多个 Python 客户端：

```bash
python3 src/client.py --host 127.0.0.1 --port 8888 --semantics at-most-once
```

如果客户端和服务端运行在不同电脑上，请将 `127.0.0.1` 替换为服务端电脑的 IP
地址，并在防火墙中允许 UDP 8888 端口的通信。

服务端电脑只需要编译并运行 `flight_server`。客户端电脑需要 `src/client.py` 和
`src/common/`，无需 C++ 编译器。完整回调演示建议使用三台电脑：一台运行 C++
服务端，另外两台分别运行 Python 监控客户端和 Python 预订客户端。

## 回调功能演示

1. 启动服务端。
2. 启动客户端 A，选择操作 4，监控航班 `1001`，监控时长设为 30 秒。
3. 在监控时间内启动客户端 B，并预订航班 `1001` 的座位。
4. 客户端 A 会立即收到回调，并显示更新后的剩余座位数。

## 调用语义实验

`--drop-first-reply` 参数用于可重复的实验演示。服务端会正常执行请求，但故意丢弃
该请求的第一次回复，迫使客户端使用相同的请求编号进行重试。

使用 at-least-once 语义启动服务端和客户端：

```bash
./flight_server --semantics at-least-once --drop-first-reply
python3 src/client.py --semantics at-least-once --timeout 0.5
```

选择操作 6，为航班 1001 增加 3 个座位。由于请求会被执行两次，剩余座位数将从
40 增加到 46。这正是非幂等操作在回复丢失和 at-least-once 语义下产生的错误结果。

接着使用 at-most-once 语义重复实验：

```bash
./flight_server --semantics at-most-once --drop-first-reply
python3 src/client.py --semantics at-most-once --timeout 0.5
```

服务端通过 `(客户端地址, 请求编号)` 检测重复请求，并直接返回缓存的回复，不会再次
执行操作，因此剩余座位数只会增加到 43。还可以使用 `--drop-first-request`、
`--request-loss-rate` 和 `--reply-loss-rate` 参数进行其他丢包实验。

## 自动测试

```bash
make test
```

测试会先编译真正用于演示的 C++ 服务端，再由 Python 客户端与它进行 UDP 通信。
测试内容包括二进制编解码（含变长 Unicode 字符串）、全部六项服务、错误回复、两个
客户端之间的回调，以及 at-least-once 与 at-most-once 两种调用语义的可观察差异。

## 项目结构

- `src/server.cpp`：C++ UDP 服务端、C++ 端二进制编解码、六项服务、回调、丢包模拟和请求历史。
- `src/client.py`：超时重试、回复匹配、回调等待循环和命令行界面。
- `src/common/message.py`：Python 客户端使用的协议头、枚举和二进制编解码器。
- `src/common/flight.py`：Python 客户端使用的航班数据模型及反序列化实现。
- `Makefile`：C++ 服务端编译和测试入口。
- `tests/test_system.py`：Python 客户端与 C++ 服务端之间的跨语言集成测试。
- `REPORT_DRAFT.md`：可用于撰写报告的设计说明和实验材料。
