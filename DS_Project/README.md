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

- macOS：使用受支持的 macOS 版本。
- C++：需要支持 C++17 的编译器。Apple Command Line Tools 提供 Apple Clang 和 `make`。
- Java 客户端：需要 JDK 11 或更新版本（需包含 `javac` 和 `java`）。
- Python 客户端及测试：需要 Python 3.10 或更新版本。
- 不需要任何第三方 C++、Java 或 Python 库。

### 在 macOS 上安装开发工具

打开“终端”（Terminal），安装 Apple Command Line Tools：

```bash
xcode-select --install
```

按照提示完成安装。检查 `make` 和 C++ 编译器是否可用：

```bash
make --version
c++ --version
```

安装 JDK 11 或更新版本。可以从 Oracle、Eclipse Temurin 等发行版安装。安装完成后，确认 `javac` 和 `java` 可从终端运行：

```bash
javac --version
java --version
```

macOS 上的 Python 版本可能较旧；如果 `python3 --version` 显示低于 3.10，请安装更新的 Python 3。

## 在 macOS 上编译

在终端中进入项目的 `DS_Project` 目录。例如，如果项目位于“文稿”文件夹：

```bash
cd ~/Documents/NTU-AY2627-6103/NTU_project/DS_Project
```

编译服务端和所有客户端：

```bash
make
```

`make` 会生成 C++ 服务端 `flight_server`、C++ 客户端 `flight_client`，以及 Java 客户端编译结果 `build/java/FlightClient.class`。

如果只需要编译 Java 客户端，可执行：

```bash
make java-client
```

如果终端提示找不到 `javac`，请检查 JDK 是否安装，以及 `javac --version` 是否能成功运行。只编译 C++ 客户端可执行 `make flight_client`；只编译服务端可执行 `make flight_server`。

## 在 macOS 上运行

在项目目录打开一个终端窗口，启动服务端：

```bash
./flight_server --host 0.0.0.0 --port 8888 --semantics at-most-once
```

保持服务端运行，再打开另一个终端窗口，在相同项目目录运行任意一个客户端：

```bash
python3 src/client.py --host 127.0.0.1 --port 8888 --semantics at-most-once
```

```bash
./flight_client --host 127.0.0.1 --port 8888
```

```bash
java -cp build/java FlightClient --host 127.0.0.1 --port 8888
```

客户端和服务端在同一台 Mac 上运行时，使用 `127.0.0.1`。若它们运行在不同电脑上，请把客户端命令中的地址替换为服务端 Mac 的 IP 地址，并确认网络及防火墙允许 UDP 8888 端口通信。

运行自动测试：

```bash
make test
```

清除编译生成的文件：

```bash
make clean
```

## 在其他系统运行

如果客户端和服务端运行在不同电脑上，请将 `127.0.0.1` 替换为服务端电脑的 IP
地址，并在防火墙中允许 UDP 8888 端口的通信。

服务端电脑只需要编译并运行 `flight_server`。Python 客户端电脑需要 `src/client.py` 和
`src/common/`，无需 C++ 编译器。完整回调演示建议使用三台电脑：一台运行 C++ 服务端，另外两台分别运行客户端监控和预订。

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
- `src/client.cpp`：C++ UDP 客户端。
- `src/java/FlightClient.java`：Java UDP 客户端。
- `src/common/message.py`：Python 客户端使用的协议头、枚举和二进制编解码器。
- `src/common/flight.py`：Python 客户端使用的航班数据模型及反序列化实现。
- `Makefile`：服务端、客户端的编译及测试入口。
- `tests/test_system.py`：Python 客户端与 C++ 服务端之间的跨语言集成测试。
- `REPORT_DRAFT.md`：可用于撰写报告的设计说明和实验材料。
