// Interactive UDP client (C++17) for the distributed flight information system.
#include <arpa/inet.h>
#include <netdb.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

#include <array>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

namespace {

using Bytes = std::vector<std::uint8_t>;
using Clock = std::chrono::steady_clock;

constexpr std::array<std::uint8_t, 4> kMagic{'F', 'L', 'I', 'T'};
constexpr std::uint8_t kVersion = 1;
constexpr std::size_t kHeaderSize = 16;
constexpr std::size_t kMaximumDatagram = 65507;

enum MessageKind : std::uint8_t { REQUEST = 1, REPLY = 2, CALLBACK = 3 };
enum Operation : std::uint8_t {
    SEARCH_FLIGHTS = 1, GET_FLIGHT = 2, RESERVE_SEATS = 3,
    MONITOR_SEATS = 4, SET_PRICE = 5, ADD_SEATS = 6,
};

struct ProtocolError : std::runtime_error { using std::runtime_error::runtime_error; };
struct RemoteError : std::runtime_error { using std::runtime_error::runtime_error; };
struct TimeoutError : std::runtime_error { using std::runtime_error::runtime_error; };
struct EndOfInput {};

class Writer {
public:
    void u8(std::uint8_t v) { data.push_back(v); }
    void u16(std::uint16_t v) { u8(v >> 8); u8(v & 0xFF); }
    void u32(std::uint32_t v) { for (int s = 24; s >= 0; s -= 8) u8((v >> s) & 0xFF); }
    void f64(double v) {
        std::uint64_t bits;
        std::memcpy(&bits, &v, sizeof bits);
        for (int s = 56; s >= 0; s -= 8) u8((bits >> s) & 0xFF);
    }
    void string(const std::string& v) {
        if (v.size() > 0xFFFF) throw ProtocolError("string is too long");
        u16(static_cast<std::uint16_t>(v.size()));
        data.insert(data.end(), v.begin(), v.end());
    }
    Bytes data;
};

class Reader {
public:
    Reader(const Bytes& d, std::size_t off = 0) : data_(d), off_(off) {}
    std::uint8_t u8() { need(1); return data_[off_++]; }
    std::uint16_t u16() { auto h = u8(); return static_cast<std::uint16_t>((h << 8) | u8()); }
    std::uint32_t u32() { std::uint32_t v = 0; for (int i = 0; i < 4; ++i) v = (v << 8) | u8(); return v; }
    double f64() {
        std::uint64_t bits = 0;
        for (int i = 0; i < 8; ++i) bits = (bits << 8) | u8();
        double v;
        std::memcpy(&v, &bits, sizeof v);
        return v;
    }
    std::string string() {
        const std::size_t n = u16();
        need(n);
        std::string s(data_.begin() + off_, data_.begin() + off_ + n);
        off_ += n;
        return s;
    }
    void finish() const { if (off_ != data_.size()) throw ProtocolError("unexpected trailing bytes"); }

private:
    void need(std::size_t n) const { if (off_ + n > data_.size()) throw ProtocolError("truncated message"); }
    const Bytes& data_;
    std::size_t off_;
};

struct Message {
    std::uint8_t kind, operation, status;
    std::uint32_t request_id;
    Bytes payload;
};

Bytes encode_message(std::uint8_t kind, std::uint8_t op, std::uint32_t id, const Bytes& payload) {
    Writer w;
    for (auto b : kMagic) w.u8(b);
    w.u8(kVersion); w.u8(kind); w.u8(op); w.u8(0);
    w.u32(id);
    w.u32(static_cast<std::uint32_t>(payload.size()));
    w.data.insert(w.data.end(), payload.begin(), payload.end());
    return w.data;
}

Message decode_message(const Bytes& d) {
    if (d.size() < kHeaderSize) throw ProtocolError("message is shorter than the protocol header");
    if (std::memcmp(d.data(), kMagic.data(), 4) != 0 || d[4] != kVersion)
        throw ProtocolError("unsupported protocol magic or version");
    Reader r(d, 5);
    Message m{};
    m.kind = r.u8(); m.operation = r.u8(); m.status = r.u8();
    m.request_id = r.u32();
    const std::uint32_t size = r.u32();
    m.payload.assign(d.begin() + kHeaderSize, d.end());
    if (size != m.payload.size()) throw ProtocolError("payload length does not match header");
    return m;
}

class Client {
public:
    Client(const std::string& host, int port, double timeout, int retries)
        : timeout_(timeout), retries_(retries) {
        addrinfo hints{}, *res = nullptr;
        hints.ai_family = AF_INET;
        hints.ai_socktype = SOCK_DGRAM;
        if (getaddrinfo(host.c_str(), nullptr, &hints, &res) != 0 || !res)
            throw std::runtime_error("cannot resolve host " + host);
        server_ = *reinterpret_cast<sockaddr_in*>(res->ai_addr);
        freeaddrinfo(res);
        server_.sin_port = htons(static_cast<std::uint16_t>(port));
        socket_ = ::socket(AF_INET, SOCK_DGRAM, 0);
        if (socket_ < 0) throw std::runtime_error("socket() failed");
        std::random_device rd;
        next_id_ = std::uniform_int_distribution<std::uint32_t>(1, 0xFFFFFFFF)(rd);
    }
    ~Client() { if (socket_ >= 0) ::close(socket_); }

    // Sends the request, retrying on timeout, and returns the success payload.
    Bytes request(std::uint8_t op, const Bytes& payload) {
        const std::uint32_t id = next_id_;
        next_id_ = id == 0xFFFFFFFF ? 1 : id + 1;
        const Bytes datagram = encode_message(REQUEST, op, id, payload);
        for (int attempt = 0; attempt <= retries_; ++attempt) {
            sendto(socket_, datagram.data(), datagram.size(), 0,
                   reinterpret_cast<const sockaddr*>(&server_), sizeof server_);
            if (attempt) std::cout << "Retry " << attempt << "/" << retries_ << " for request " << id << "\n";
            const auto deadline = Clock::now() + std::chrono::duration_cast<Clock::duration>(
                                                     std::chrono::duration<double>(timeout_));
            Bytes data;
            while (receive(data, deadline)) {
                Message m;
                try { m = decode_message(data); } catch (const ProtocolError&) { continue; }
                if (m.kind != REPLY || m.request_id != id || m.operation != op) continue;
                if (m.status != 0) {
                    Reader r(m.payload);
                    throw RemoteError(r.string());
                }
                return m.payload;
            }
        }
        throw TimeoutError("server did not reply after " + std::to_string(retries_ + 1) + " attempt(s)");
    }

    // Blocks until the deadline, printing seat callbacks for the given flight.
    void wait_for_callbacks(std::uint32_t flight_id, double interval) {
        const auto deadline = Clock::now() + std::chrono::duration_cast<Clock::duration>(
                                                 std::chrono::duration<double>(interval));
        Bytes data;
        while (receive(data, deadline)) {
            try {
                Message m = decode_message(data);
                if (m.kind != CALLBACK || m.operation != MONITOR_SEATS || m.status != 0) continue;
                Reader r(m.payload);
                const auto id = r.u32();
                const auto seats = r.u32();
                r.finish();
                if (id == flight_id)
                    std::cout << "Callback: flight " << id << " now has " << seats << " seat(s) available\n";
            } catch (const ProtocolError&) {}
        }
        std::cout << "Monitor interval ended.\n";
    }

private:
    // Receives one datagram from the server before the deadline.
    bool receive(Bytes& out, Clock::time_point deadline) {
        for (;;) {
            const auto remaining = std::chrono::duration_cast<std::chrono::microseconds>(deadline - Clock::now());
            if (remaining.count() <= 0) return false;
            timeval tv{static_cast<time_t>(remaining.count() / 1000000),
                       static_cast<suseconds_t>(remaining.count() % 1000000)};
            setsockopt(socket_, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
            Bytes buf(kMaximumDatagram);
            sockaddr_in from{};
            socklen_t len = sizeof from;
            const ssize_t n = recvfrom(socket_, buf.data(), buf.size(), 0,
                                       reinterpret_cast<sockaddr*>(&from), &len);
            if (n < 0) {
                if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) continue;
                return false;
            }
            if (from.sin_addr.s_addr != server_.sin_addr.s_addr || from.sin_port != server_.sin_port) continue;
            buf.resize(static_cast<std::size_t>(n));
            out = std::move(buf);
            return true;
        }
    }

    double timeout_;
    int retries_;
    int socket_ = -1;
    sockaddr_in server_{};
    std::uint32_t next_id_ = 1;
};

template <typename T>
T prompt(const std::string& text) {
    std::cout << text << std::flush;
    std::string line;
    if (!std::getline(std::cin, line)) throw EndOfInput();
    std::size_t used = 0;
    if constexpr (std::is_same_v<T, double>) {
        const double v = std::stod(line, &used);
        return v;
    } else {
        const long long v = std::stoll(line, &used);
        if (v < 0 || v > std::numeric_limits<std::uint32_t>::max()) throw std::invalid_argument("out of range");
        return static_cast<T>(v);
    }
}

std::string read_line(const std::string& text) {
    std::cout << text << std::flush;
    std::string line;
    if (!std::getline(std::cin, line)) throw EndOfInput();
    const auto b = line.find_first_not_of(" \t\r\n");
    const auto e = line.find_last_not_of(" \t\r\n");
    return b == std::string::npos ? "" : line.substr(b, e - b + 1);
}

void run_menu(Client& client) {
    for (;;) {
        std::cout << "\n1. Search flight identifiers by route\n2. Query flight details\n3. Reserve seats\n"
                     "4. Monitor seat updates\n5. Set airfare (additional idempotent operation)\n"
                     "6. Add seats (additional non-idempotent operation)\n0. Exit\n";
        const std::string choice = read_line("Select an operation: ");
        try {
            if (choice == "0") { std::cout << "Client terminated.\n"; return; }
            Writer w;
            if (choice == "1") {
                w.string(read_line("Source: "));
                w.string(read_line("Destination: "));
                const Bytes reply = client.request(SEARCH_FLIGHTS, w.data);
                Reader r(reply);
                const std::uint16_t count = r.u16();
                std::cout << "Matching flight identifier(s):";
                for (std::uint16_t i = 0; i < count; ++i) std::cout << (i ? ", " : " ") << r.u32();
                r.finish();
                std::cout << "\n";
            } else if (choice == "2") {
                w.u32(prompt<std::uint32_t>("Flight identifier: "));
                const Bytes reply = client.request(GET_FLIGHT, w.data);
                Reader r(reply);
                const auto id = r.u32();
                const auto source = r.string();
                const auto destination = r.string();
                const int hour = r.u8(), minute = r.u8();
                const double price = r.f64();
                const auto seats = r.u32();
                r.finish();
                char line[256];
                std::snprintf(line, sizeof line, "%02d:%02d", hour, minute);
                std::cout << "Flight " << id << ": " << source << " -> " << destination
                          << ", departure " << line;
                std::snprintf(line, sizeof line, "%.2f", price);
                std::cout << ", fare $" << line << ", " << seats << " seat(s) available\n";
            } else if (choice == "3" || choice == "6") {
                const bool reserve = choice == "3";
                w.u32(prompt<std::uint32_t>("Flight identifier: "));
                w.u32(prompt<std::uint32_t>(reserve ? "Seats to reserve: " : "Seats to add: "));
                const Bytes reply = client.request(reserve ? RESERVE_SEATS : ADD_SEATS, w.data);
                Reader r(reply);
                r.u32();
                const auto changed = r.u32();
                const auto seats = r.u32();
                r.finish();
                if (reserve)
                    std::cout << "Reservation confirmed: " << changed << " seat(s); " << seats << " remaining.\n";
                else
                    std::cout << "Added " << changed << " seat(s); " << seats << " now available.\n";
            } else if (choice == "4") {
                const auto flight_id = prompt<std::uint32_t>("Flight identifier: ");
                const double interval = prompt<double>("Monitor interval in seconds: ");
                w.u32(flight_id);
                w.f64(interval);
                const Bytes reply = client.request(MONITOR_SEATS, w.data);
                Reader r(reply);
                r.u32();
                const double registered = r.f64();
                const auto seats = r.u32();
                r.finish();
                char line[64];
                std::snprintf(line, sizeof line, "%.1f", registered);
                std::cout << "Monitoring flight " << flight_id << " for " << line
                          << "s; current availability is " << seats << " seat(s).\n";
                client.wait_for_callbacks(flight_id, interval);
            } else if (choice == "5") {
                w.u32(prompt<std::uint32_t>("Flight identifier: "));
                w.f64(prompt<double>("New airfare: "));
                const Bytes reply = client.request(SET_PRICE, w.data);
                Reader r(reply);
                r.u32();
                const double price = r.f64();
                r.finish();
                char line[64];
                std::snprintf(line, sizeof line, "%.2f", price);
                std::cout << "Fare updated to $" << line << ".\n";
            } else {
                std::cout << "Unknown menu choice.\n";
            }
        } catch (const EndOfInput&) {
            return;
        } catch (const std::exception& e) {
            std::cout << "Error: " << e.what() << "\n";
        }
    }
}

struct Options {
    std::string host = "127.0.0.1";
    int port = 8888;
    double timeout = 1.0;
    int retries = 4;
};

}  // namespace

int main(int argc, char** argv) {
    Options opt;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        auto value = [&]() -> std::string {
            if (i + 1 >= argc) throw std::invalid_argument("missing value for " + arg);
            return argv[++i];
        };
        try {
            if (arg == "--host" || arg == "-h") opt.host = value();
            else if (arg == "--port" || arg == "-p") opt.port = std::stoi(value());
            else if (arg == "--timeout" || arg == "-t") opt.timeout = std::stod(value());
            else if (arg == "--retries" || arg == "-r") opt.retries = std::stoi(value());
            else if (arg == "--semantics" || arg == "-s") value();  // semantics is enforced by the server
            else throw std::invalid_argument("unknown option " + arg);
        } catch (const std::exception& e) {
            std::cerr << "Error: " << e.what() << "\n";
            return 2;
        }
    }
    if (opt.timeout <= 0 || opt.retries < 0) {
        std::cerr << "Error: timeout must be positive and retries cannot be negative\n";
        return 2;
    }
    try {
        Client client(opt.host, opt.port, opt.timeout, opt.retries);
        run_menu(client);
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
