#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <cerrno>
#include <cctype>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <iomanip>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace {

constexpr std::array<std::uint8_t, 4> kMagic{'F', 'L', 'I', 'T'};
constexpr std::uint8_t kVersion = 1;
constexpr std::size_t kHeaderSize = 16;
constexpr std::size_t kMaximumPayload = 60000;
constexpr std::size_t kMaximumDatagram = 65507;

enum MessageKind : std::uint8_t {
    REQUEST = 1,
    REPLY = 2,
    CALLBACK = 3,
};

enum Operation : std::uint8_t {
    SEARCH_FLIGHTS = 1,
    GET_FLIGHT = 2,
    RESERVE_SEATS = 3,
    MONITOR_SEATS = 4,
    SET_PRICE = 5,
    ADD_SEATS = 6,
};

enum Status : std::uint8_t {
    OK = 0,
    BAD_REQUEST = 1,
    NOT_FOUND = 2,
    INSUFFICIENT_SEATS = 3,
    INTERNAL_ERROR = 4,
};

const char* operation_name(std::uint8_t operation) {
    switch (operation) {
        case SEARCH_FLIGHTS: return "SEARCH_FLIGHTS";
        case GET_FLIGHT: return "GET_FLIGHT";
        case RESERVE_SEATS: return "RESERVE_SEATS";
        case MONITOR_SEATS: return "MONITOR_SEATS";
        case SET_PRICE: return "SET_PRICE";
        case ADD_SEATS: return "ADD_SEATS";
        default: return "UNKNOWN";
    }
}

const char* status_name(std::uint8_t status) {
    switch (status) {
        case OK: return "OK";
        case BAD_REQUEST: return "BAD_REQUEST";
        case NOT_FOUND: return "NOT_FOUND";
        case INSUFFICIENT_SEATS: return "INSUFFICIENT_SEATS";
        case INTERNAL_ERROR: return "INTERNAL_ERROR";
        default: return "UNKNOWN";
    }
}

class ProtocolError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

class BinaryWriter {
public:
    void u8(std::uint8_t value) { data_.push_back(value); }

    void u16(std::uint16_t value) {
        data_.push_back(static_cast<std::uint8_t>(value >> 8));
        data_.push_back(static_cast<std::uint8_t>(value));
    }

    void u32(std::uint32_t value) {
        for (int shift = 24; shift >= 0; shift -= 8) {
            data_.push_back(static_cast<std::uint8_t>(value >> shift));
        }
    }

    void u64(std::uint64_t value) {
        for (int shift = 56; shift >= 0; shift -= 8) {
            data_.push_back(static_cast<std::uint8_t>(value >> shift));
        }
    }

    void f64(double value) {
        std::uint64_t bits = 0;
        static_assert(sizeof(bits) == sizeof(value), "unexpected double size");
        std::memcpy(&bits, &value, sizeof(bits));
        u64(bits);
    }

    void string(const std::string& value) {
        if (value.size() > std::numeric_limits<std::uint16_t>::max()) {
            throw ProtocolError("string is too long");
        }
        u16(static_cast<std::uint16_t>(value.size()));
        data_.insert(data_.end(), value.begin(), value.end());
    }

    void bytes(const std::vector<std::uint8_t>& value) {
        data_.insert(data_.end(), value.begin(), value.end());
    }

    std::vector<std::uint8_t> build() && { return std::move(data_); }

private:
    std::vector<std::uint8_t> data_;
};

class BinaryReader {
public:
    explicit BinaryReader(const std::vector<std::uint8_t>& data, std::size_t offset = 0)
        : data_(data), offset_(offset) {}

    std::uint8_t u8() {
        require(1);
        return data_[offset_++];
    }

    std::uint16_t u16() {
        require(2);
        const auto value = static_cast<std::uint16_t>(
            (static_cast<std::uint16_t>(data_[offset_]) << 8) |
            static_cast<std::uint16_t>(data_[offset_ + 1]));
        offset_ += 2;
        return value;
    }

    std::uint32_t u32() {
        require(4);
        std::uint32_t value = 0;
        for (int i = 0; i < 4; ++i) {
            value = (value << 8) | data_[offset_++];
        }
        return value;
    }

    std::uint64_t u64() {
        require(8);
        std::uint64_t value = 0;
        for (int i = 0; i < 8; ++i) {
            value = (value << 8) | data_[offset_++];
        }
        return value;
    }

    double f64() {
        const std::uint64_t bits = u64();
        double value = 0.0;
        std::memcpy(&value, &bits, sizeof(value));
        return value;
    }

    std::string string() {
        const std::size_t size = u16();
        require(size);
        std::string value(data_.begin() + static_cast<std::ptrdiff_t>(offset_),
                          data_.begin() + static_cast<std::ptrdiff_t>(offset_ + size));
        offset_ += size;
        return value;
    }

    void finish() const {
        if (offset_ != data_.size()) {
            throw ProtocolError("unexpected trailing bytes");
        }
    }

private:
    void require(std::size_t size) const {
        if (size > data_.size() - offset_) {
            throw ProtocolError("truncated message");
        }
    }

    const std::vector<std::uint8_t>& data_;
    std::size_t offset_;
};

struct Message {
    std::uint8_t kind;
    std::uint8_t operation;
    std::uint8_t status;
    std::uint32_t request_id;
    std::vector<std::uint8_t> payload;
};

std::vector<std::uint8_t> encode_message(
    std::uint8_t kind,
    std::uint8_t operation,
    std::uint8_t status,
    std::uint32_t request_id,
    const std::vector<std::uint8_t>& payload) {
    if (payload.size() > kMaximumPayload) {
        throw ProtocolError("payload is too large for a UDP message");
    }
    BinaryWriter writer;
    for (const auto byte : kMagic) writer.u8(byte);
    writer.u8(kVersion);
    writer.u8(kind);
    writer.u8(operation);
    writer.u8(status);
    writer.u32(request_id);
    writer.u32(static_cast<std::uint32_t>(payload.size()));
    writer.bytes(payload);
    return std::move(writer).build();
}

Message decode_message(const std::vector<std::uint8_t>& data) {
    if (data.size() < kHeaderSize) {
        throw ProtocolError("message is shorter than the protocol header");
    }
    BinaryReader reader(data);
    for (const auto expected : kMagic) {
        if (reader.u8() != expected) throw ProtocolError("invalid protocol magic");
    }
    if (reader.u8() != kVersion) throw ProtocolError("unsupported protocol version");
    Message message{};
    message.kind = reader.u8();
    message.operation = reader.u8();
    message.status = reader.u8();
    message.request_id = reader.u32();
    const std::size_t payload_size = reader.u32();
    if (payload_size != data.size() - kHeaderSize) {
        throw ProtocolError("payload length does not match header");
    }
    message.payload.assign(data.begin() + static_cast<std::ptrdiff_t>(kHeaderSize), data.end());
    return message;
}

std::vector<std::uint8_t> encode_error(const std::string& message) {
    BinaryWriter writer;
    writer.string(message);
    return std::move(writer).build();
}

struct Flight {
    std::uint32_t flight_id;
    std::string source;
    std::string destination;
    std::uint8_t hour;
    std::uint8_t minute;
    double price;
    std::uint32_t seats;

    void marshal(BinaryWriter& writer) const {
        writer.u32(flight_id);
        writer.string(source);
        writer.string(destination);
        writer.u8(hour);
        writer.u8(minute);
        writer.f64(price);
        writer.u32(seats);
    }
};

struct RequestKey {
    std::uint32_t address;
    std::uint16_t port;
    std::uint32_t request_id;

    bool operator==(const RequestKey& other) const {
        return address == other.address && port == other.port && request_id == other.request_id;
    }
};

struct RequestKeyHash {
    std::size_t operator()(const RequestKey& key) const noexcept {
        std::size_t value = key.address;
        value ^= static_cast<std::size_t>(key.port) << 1;
        value ^= static_cast<std::size_t>(key.request_id) << 17;
        return value;
    }
};

struct HistoryEntry {
    std::vector<std::uint8_t> request;
    std::vector<std::uint8_t> reply;
};

struct MonitorRegistration {
    sockaddr_in client_address{};
    std::uint32_t flight_id{};
    std::chrono::steady_clock::time_point expires_at{};
};

class ServiceFailure : public std::runtime_error {
public:
    ServiceFailure(std::uint8_t status_value, const std::string& message)
        : std::runtime_error(message), status(status_value) {}
    std::uint8_t status;
};

std::string endpoint(const sockaddr_in& address) {
    std::array<char, INET_ADDRSTRLEN> buffer{};
    inet_ntop(AF_INET, &address.sin_addr, buffer.data(), buffer.size());
    return std::string(buffer.data()) + ":" + std::to_string(ntohs(address.sin_port));
}

RequestKey request_key(const sockaddr_in& address, std::uint32_t request_id) {
    return {address.sin_addr.s_addr, address.sin_port, request_id};
}

bool same_client(const sockaddr_in& left, const sockaddr_in& right) {
    return left.sin_addr.s_addr == right.sin_addr.s_addr && left.sin_port == right.sin_port;
}

std::string ascii_lower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char character) {
        return static_cast<char>(std::tolower(character));
    });
    return value;
}

struct Options {
    std::string host = "0.0.0.0";
    std::uint16_t port = 8888;
    std::string semantics = "at-most-once";
    double request_loss_rate = 0.0;
    double reply_loss_rate = 0.0;
    bool drop_first_request = false;
    bool drop_first_reply = false;
    std::uint32_t random_seed = std::random_device{}();
};

void print_help(const char* program) {
    std::cout
        << "Usage: " << program << " [options]\n"
        << "  --host ADDRESS                 IPv4 address to bind (default 0.0.0.0)\n"
        << "  --port PORT                    UDP port (default 8888)\n"
        << "  --semantics MODE               at-least-once or at-most-once\n"
        << "  --request-loss-rate RATE       probability from 0 to 1\n"
        << "  --reply-loss-rate RATE         probability from 0 to 1\n"
        << "  --drop-first-request           drop first copy of every request ID\n"
        << "  --drop-first-reply             drop first reply for every request ID\n"
        << "  --random-seed INTEGER          reproducible probabilistic loss\n";
}

Options parse_options(int argc, char* argv[]) {
    Options options;
    auto next_value = [&](int& index, const std::string& option) -> std::string {
        if (++index >= argc) throw std::invalid_argument("missing value for " + option);
        return argv[index];
    };
    for (int index = 1; index < argc; ++index) {
        const std::string argument = argv[index];
        if (argument == "--help" || argument == "-h") {
            print_help(argv[0]);
            std::exit(0);
        } else if (argument == "--host") {
            options.host = next_value(index, argument);
        } else if (argument == "--port") {
            const auto value = std::stoul(next_value(index, argument));
            if (value > 65535) throw std::invalid_argument("port must be at most 65535");
            options.port = static_cast<std::uint16_t>(value);
        } else if (argument == "--semantics") {
            options.semantics = next_value(index, argument);
        } else if (argument == "--request-loss-rate") {
            options.request_loss_rate = std::stod(next_value(index, argument));
        } else if (argument == "--reply-loss-rate") {
            options.reply_loss_rate = std::stod(next_value(index, argument));
        } else if (argument == "--drop-first-request") {
            options.drop_first_request = true;
        } else if (argument == "--drop-first-reply") {
            options.drop_first_reply = true;
        } else if (argument == "--random-seed") {
            options.random_seed = static_cast<std::uint32_t>(
                std::stoul(next_value(index, argument)));
        } else {
            throw std::invalid_argument("unknown option: " + argument);
        }
    }
    if (options.semantics != "at-least-once" && options.semantics != "at-most-once") {
        throw std::invalid_argument("semantics must be at-least-once or at-most-once");
    }
    if (!std::isfinite(options.request_loss_rate) || options.request_loss_rate < 0.0 ||
        options.request_loss_rate > 1.0 || !std::isfinite(options.reply_loss_rate) ||
        options.reply_loss_rate < 0.0 || options.reply_loss_rate > 1.0) {
        throw std::invalid_argument("loss rates must be between 0 and 1");
    }
    return options;
}

volatile std::sig_atomic_t stop_requested = 0;

void handle_signal(int) { stop_requested = 1; }

class FlightServer {
public:
    explicit FlightServer(Options options)
        : options_(std::move(options)), random_(options_.random_seed) {
        flights_.emplace(1001, Flight{1001, "Singapore", "Tokyo", 8, 30, 620.00, 40});
        flights_.emplace(1002, Flight{1002, "Singapore", "Tokyo", 19, 15, 575.50, 25});
        flights_.emplace(2001, Flight{2001, "Singapore", "London", 23, 5, 1280.00, 18});
        flights_.emplace(3001, Flight{3001, "Bangkok", "Singapore", 14, 45, 210.00, 32});

        socket_ = ::socket(AF_INET, SOCK_DGRAM, 0);
        if (socket_ < 0) throw_system_error("socket");
        const int enabled = 1;
        setsockopt(socket_, SOL_SOCKET, SO_REUSEADDR, &enabled, sizeof(enabled));
        timeval timeout{0, 200000};
        setsockopt(socket_, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));

        sockaddr_in address{};
        address.sin_family = AF_INET;
        address.sin_port = htons(options_.port);
        if (inet_pton(AF_INET, options_.host.c_str(), &address.sin_addr) != 1) {
            close_socket();
            throw std::invalid_argument("--host must be an IPv4 address");
        }
        if (::bind(socket_, reinterpret_cast<sockaddr*>(&address), sizeof(address)) < 0) {
            close_socket();
            throw_system_error("bind");
        }

        socklen_t length = sizeof(bound_address_);
        if (getsockname(socket_, reinterpret_cast<sockaddr*>(&bound_address_), &length) < 0) {
            close_socket();
            throw_system_error("getsockname");
        }
    }

    ~FlightServer() { close_socket(); }

    FlightServer(const FlightServer&) = delete;
    FlightServer& operator=(const FlightServer&) = delete;

    void serve_forever() {
        std::cout << "C++ flight server listening on " << endpoint(bound_address_)
                  << " with " << options_.semantics << " semantics\n";
        std::vector<std::uint8_t> buffer(kMaximumDatagram);
        while (!stop_requested) {
            sockaddr_in client{};
            socklen_t client_length = sizeof(client);
            const ssize_t received = recvfrom(
                socket_, buffer.data(), buffer.size(), 0,
                reinterpret_cast<sockaddr*>(&client), &client_length);
            if (received < 0) {
                remove_expired_monitors();
                continue;
            }
            std::vector<std::uint8_t> datagram(
                buffer.begin(), buffer.begin() + static_cast<std::ptrdiff_t>(received));
            process_datagram(datagram, client);
        }
    }

private:
    [[noreturn]] static void throw_system_error(const std::string& operation) {
        throw std::runtime_error(operation + " failed: " + std::strerror(errno));
    }

    void close_socket() {
        if (socket_ >= 0) {
            ::close(socket_);
            socket_ = -1;
        }
    }

    void process_datagram(
        const std::vector<std::uint8_t>& datagram,
        const sockaddr_in& client) {
        Message request{};
        try {
            request = decode_message(datagram);
        } catch (const ProtocolError& error) {
            std::cout << "Discarded malformed datagram from " << endpoint(client)
                      << ": " << error.what() << '\n';
            return;
        }
        if (request.kind != REQUEST || request.operation < SEARCH_FLIGHTS ||
            request.operation > ADD_SEATS) {
            std::cout << "Discarded invalid request from " << endpoint(client) << '\n';
            return;
        }

        const RequestKey key = request_key(client, request.request_id);
        if (should_drop_request(key)) {
            std::cout << "SIMULATED REQUEST LOSS id=" << request.request_id
                      << " from=" << endpoint(client) << '\n';
            return;
        }

        std::cout << "REQUEST id=" << request.request_id
                  << " operation=" << operation_name(request.operation)
                  << " from=" << endpoint(client) << '\n';

        if (options_.semantics == "at-most-once") {
            const auto found = history_.find(key);
            if (found != history_.end()) {
                std::vector<std::uint8_t> reply;
                if (found->second.request != datagram) {
                    reply = encode_message(
                        REPLY, request.operation, BAD_REQUEST, request.request_id,
                        encode_error("request identifier was reused with different arguments"));
                } else {
                    reply = found->second.reply;
                    std::cout << "DUPLICATE id=" << request.request_id
                              << ": returning cached reply\n";
                }
                send_reply(reply, client, key);
                return;
            }
        }

        std::vector<std::uint8_t> reply;
        try {
            const auto payload = perform(request.operation, request.payload, client);
            reply = encode_message(REPLY, request.operation, OK, request.request_id, payload);
        } catch (const ServiceFailure& error) {
            reply = encode_message(
                REPLY, request.operation, error.status, request.request_id,
                encode_error(error.what()));
        } catch (const ProtocolError& error) {
            reply = encode_message(
                REPLY, request.operation, BAD_REQUEST, request.request_id,
                encode_error(std::string("invalid request: ") + error.what()));
        } catch (const std::exception& error) {
            std::cerr << "INTERNAL ERROR id=" << request.request_id
                      << ": " << error.what() << '\n';
            reply = encode_message(
                REPLY, request.operation, INTERNAL_ERROR, request.request_id,
                encode_error("internal server error"));
        }

        if (options_.semantics == "at-most-once") {
            history_.emplace(key, HistoryEntry{datagram, reply});
            history_order_.push_back(key);
            while (history_order_.size() > history_limit_) {
                history_.erase(history_order_.front());
                history_order_.pop_front();
            }
        }
        send_reply(reply, client, key);
    }

    std::vector<std::uint8_t> perform(
        std::uint8_t operation,
        const std::vector<std::uint8_t>& payload,
        const sockaddr_in& client) {
        BinaryReader reader(payload);
        BinaryWriter writer;

        if (operation == SEARCH_FLIGHTS) {
            const std::string source = ascii_lower(reader.string());
            const std::string destination = ascii_lower(reader.string());
            reader.finish();
            std::vector<std::uint32_t> matches;
            for (const auto& item : flights_) {
                const Flight& flight = item.second;
                if (ascii_lower(flight.source) == source &&
                    ascii_lower(flight.destination) == destination) {
                    matches.push_back(flight.flight_id);
                }
            }
            std::sort(matches.begin(), matches.end());
            if (matches.empty()) {
                throw ServiceFailure(NOT_FOUND, "no matching flights found");
            }
            writer.u16(static_cast<std::uint16_t>(matches.size()));
            for (const auto flight_id : matches) writer.u32(flight_id);

        } else if (operation == GET_FLIGHT) {
            const auto flight_id = reader.u32();
            reader.finish();
            get_flight(flight_id).marshal(writer);

        } else if (operation == RESERVE_SEATS) {
            const auto flight_id = reader.u32();
            const auto count = reader.u32();
            reader.finish();
            Flight& flight = get_flight(flight_id);
            if (count == 0) throw ServiceFailure(BAD_REQUEST, "seat count must be positive");
            if (count > flight.seats) {
                throw ServiceFailure(
                    INSUFFICIENT_SEATS,
                    "only " + std::to_string(flight.seats) + " seat(s) are available");
            }
            flight.seats -= count;
            writer.u32(flight.flight_id);
            writer.u32(count);
            writer.u32(flight.seats);
            notify_monitors(flight);

        } else if (operation == MONITOR_SEATS) {
            const auto flight_id = reader.u32();
            const double interval = reader.f64();
            reader.finish();
            Flight& flight = get_flight(flight_id);
            if (!std::isfinite(interval) || interval <= 0.0 || interval > 3600.0) {
                throw ServiceFailure(
                    BAD_REQUEST,
                    "monitor interval must be greater than 0 and at most 3600 seconds");
            }
            remove_expired_monitors();
            monitors_.erase(
                std::remove_if(
                    monitors_.begin(), monitors_.end(), [&](const MonitorRegistration& item) {
                        return same_client(item.client_address, client) &&
                               item.flight_id == flight_id;
                    }),
                monitors_.end());
            const auto duration = std::chrono::duration_cast<std::chrono::steady_clock::duration>(
                std::chrono::duration<double>(interval));
            monitors_.push_back({client, flight_id, std::chrono::steady_clock::now() + duration});
            writer.u32(flight.flight_id);
            writer.f64(interval);
            writer.u32(flight.seats);

        } else if (operation == SET_PRICE) {
            const auto flight_id = reader.u32();
            const double price = reader.f64();
            reader.finish();
            Flight& flight = get_flight(flight_id);
            if (!std::isfinite(price) || price < 0.0) {
                throw ServiceFailure(BAD_REQUEST, "price cannot be negative or non-finite");
            }
            flight.price = price;
            writer.u32(flight.flight_id);
            writer.f64(flight.price);

        } else if (operation == ADD_SEATS) {
            const auto flight_id = reader.u32();
            const auto count = reader.u32();
            reader.finish();
            Flight& flight = get_flight(flight_id);
            if (count == 0) throw ServiceFailure(BAD_REQUEST, "seat count must be positive");
            if (count > std::numeric_limits<std::uint32_t>::max() - flight.seats) {
                throw ServiceFailure(BAD_REQUEST, "seat count would overflow");
            }
            flight.seats += count;
            writer.u32(flight.flight_id);
            writer.u32(count);
            writer.u32(flight.seats);
            notify_monitors(flight);
        } else {
            throw ServiceFailure(BAD_REQUEST, "unsupported operation");
        }
        return std::move(writer).build();
    }

    Flight& get_flight(std::uint32_t flight_id) {
        const auto found = flights_.find(flight_id);
        if (found == flights_.end()) {
            throw ServiceFailure(
                NOT_FOUND, "flight " + std::to_string(flight_id) + " does not exist");
        }
        return found->second;
    }

    void remove_expired_monitors() {
        const auto now = std::chrono::steady_clock::now();
        monitors_.erase(
            std::remove_if(
                monitors_.begin(), monitors_.end(),
                [&](const MonitorRegistration& item) { return item.expires_at <= now; }),
            monitors_.end());
    }

    void notify_monitors(const Flight& flight) {
        remove_expired_monitors();
        BinaryWriter writer;
        writer.u32(flight.flight_id);
        writer.u32(flight.seats);
        const auto callback = encode_message(
            CALLBACK, MONITOR_SEATS, OK, 0, std::move(writer).build());
        for (const auto& monitor : monitors_) {
            if (monitor.flight_id != flight.flight_id) continue;
            sendto(
                socket_, callback.data(), callback.size(), 0,
                reinterpret_cast<const sockaddr*>(&monitor.client_address),
                sizeof(monitor.client_address));
            std::cout << "CALLBACK flight=" << flight.flight_id
                      << " seats=" << flight.seats
                      << " to=" << endpoint(monitor.client_address) << '\n';
        }
    }

    bool random_loss(double rate) {
        if (rate <= 0.0) return false;
        return std::bernoulli_distribution(rate)(random_);
    }

    bool should_drop_request(const RequestKey& key) {
        if (options_.drop_first_request && dropped_requests_.insert(key).second) return true;
        return random_loss(options_.request_loss_rate);
    }

    void send_reply(
        const std::vector<std::uint8_t>& reply,
        const sockaddr_in& client,
        const RequestKey& key) {
        const Message decoded = decode_message(reply);
        if (options_.drop_first_reply && dropped_replies_.insert(key).second) {
            std::cout << "SIMULATED REPLY LOSS id=" << key.request_id
                      << " to=" << endpoint(client) << '\n';
            return;
        }
        if (random_loss(options_.reply_loss_rate)) {
            std::cout << "SIMULATED REPLY LOSS id=" << key.request_id
                      << " to=" << endpoint(client) << '\n';
            return;
        }
        const ssize_t sent = sendto(
            socket_, reply.data(), reply.size(), 0,
            reinterpret_cast<const sockaddr*>(&client), sizeof(client));
        if (sent < 0) {
            std::cerr << "sendto failed: " << std::strerror(errno) << '\n';
            return;
        }
        std::cout << "REPLY id=" << key.request_id
                  << " operation=" << operation_name(decoded.operation)
                  << " status=" << status_name(decoded.status)
                  << " to=" << endpoint(client) << '\n';
    }

    Options options_;
    int socket_ = -1;
    sockaddr_in bound_address_{};
    std::unordered_map<std::uint32_t, Flight> flights_;
    std::vector<MonitorRegistration> monitors_;
    std::unordered_map<RequestKey, HistoryEntry, RequestKeyHash> history_;
    std::deque<RequestKey> history_order_;
    const std::size_t history_limit_ = 2048;
    std::unordered_set<RequestKey, RequestKeyHash> dropped_requests_;
    std::unordered_set<RequestKey, RequestKeyHash> dropped_replies_;
    std::mt19937 random_;
};

}  // namespace

int main(int argc, char* argv[]) {
    try {
        std::signal(SIGINT, handle_signal);
        std::signal(SIGTERM, handle_signal);
        FlightServer server(parse_options(argc, argv));
        server.serve_forever();
        std::cout << "Server stopped.\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Error: " << error.what() << '\n';
        return 1;
    }
}
