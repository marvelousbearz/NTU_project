import java.io.BufferedReader;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.SocketTimeoutException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.Locale;

/** Interactive UDP client (Java 11+) for the distributed flight information system. */
public class FlightClient {
    private static final byte[] MAGIC = {'F', 'L', 'I', 'T'};
    private static final int VERSION = 1;
    private static final int HEADER_SIZE = 16;
    private static final int MAX_DATAGRAM = 65507;

    private static final int REQUEST = 1, REPLY = 2, CALLBACK = 3;
    private static final int SEARCH_FLIGHTS = 1, GET_FLIGHT = 2, RESERVE_SEATS = 3,
            MONITOR_SEATS = 4, SET_PRICE = 5, ADD_SEATS = 6;

    static class RemoteException extends Exception {
        RemoteException(String message) { super(message); }
    }

    static class Message {
        int kind, operation, status;
        long requestId;
        ByteBuffer payload;
    }

    /** Big-endian payload writer. */
    static class Writer {
        private final java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();

        Writer u32(long v) {
            out.writeBytes(ByteBuffer.allocate(4).putInt((int) v).array());
            return this;
        }

        Writer f64(double v) {
            out.writeBytes(ByteBuffer.allocate(8).putDouble(v).array());
            return this;
        }

        Writer string(String s) {
            byte[] b = s.getBytes(StandardCharsets.UTF_8);
            if (b.length > 0xFFFF) throw new IllegalArgumentException("string is too long");
            out.write(b.length >> 8);
            out.write(b.length & 0xFF);
            out.writeBytes(b);
            return this;
        }

        byte[] build() { return out.toByteArray(); }
    }

    /** Big-endian payload reader; buffer underflow surfaces as a RuntimeException. */
    static class Reader {
        private final ByteBuffer buf;

        Reader(ByteBuffer buf) { this.buf = buf; }

        int u8() { return buf.get() & 0xFF; }
        int u16() { return buf.getShort() & 0xFFFF; }
        long u32() { return buf.getInt() & 0xFFFFFFFFL; }
        double f64() { return buf.getDouble(); }

        String string() {
            byte[] b = new byte[u16()];
            buf.get(b);
            return new String(b, StandardCharsets.UTF_8);
        }

        void finish() {
            if (buf.hasRemaining()) throw new IllegalStateException("unexpected trailing bytes");
        }
    }

    private final DatagramSocket socket;
    private final InetAddress serverHost;
    private final int serverPort;
    private final int timeoutMs;
    private final int retries;
    private long nextRequestId = new SecureRandom().nextInt(Integer.MAX_VALUE) + 1L;

    FlightClient(String host, int port, double timeoutSeconds, int retries) throws IOException {
        this.serverHost = InetAddress.getByName(host);
        this.serverPort = port;
        this.timeoutMs = (int) Math.max(1, Math.round(timeoutSeconds * 1000));
        this.retries = retries;
        this.socket = new DatagramSocket();
    }

    private static byte[] encode(int kind, int operation, long requestId, byte[] payload) {
        ByteBuffer b = ByteBuffer.allocate(HEADER_SIZE + payload.length);
        b.put(MAGIC).put((byte) VERSION).put((byte) kind).put((byte) operation).put((byte) 0);
        b.putInt((int) requestId).putInt(payload.length).put(payload);
        return b.array();
    }

    /** Returns null for datagrams that are not valid protocol messages. */
    private static Message decode(byte[] data, int length) {
        if (length < HEADER_SIZE) return null;
        ByteBuffer b = ByteBuffer.wrap(data, 0, length);
        for (byte m : MAGIC) if (b.get() != m) return null;
        if (b.get() != VERSION) return null;
        Message msg = new Message();
        msg.kind = b.get() & 0xFF;
        msg.operation = b.get() & 0xFF;
        msg.status = b.get() & 0xFF;
        msg.requestId = b.getInt() & 0xFFFFFFFFL;
        long size = b.getInt() & 0xFFFFFFFFL;
        if (size != length - HEADER_SIZE) return null;
        msg.payload = b.slice();
        return msg;
    }

    private Message receive(long deadlineNanos) throws IOException {
        byte[] buf = new byte[MAX_DATAGRAM];
        while (true) {
            long remainingMs = (deadlineNanos - System.nanoTime()) / 1_000_000L;
            if (remainingMs <= 0) return null;
            socket.setSoTimeout((int) remainingMs);
            DatagramPacket packet = new DatagramPacket(buf, buf.length);
            try {
                socket.receive(packet);
            } catch (SocketTimeoutException e) {
                return null;
            }
            if (!packet.getAddress().equals(serverHost) || packet.getPort() != serverPort) continue;
            Message msg = decode(packet.getData(), packet.getLength());
            if (msg != null) return msg;
        }
    }

    /** Sends the request, retrying on timeout, and returns a reader over the success payload. */
    Reader request(int operation, byte[] payload) throws IOException, RemoteException {
        long id = nextRequestId;
        nextRequestId = id == 0xFFFFFFFFL ? 1 : id + 1;
        byte[] datagram = encode(REQUEST, operation, id, payload);
        for (int attempt = 0; attempt <= retries; attempt++) {
            socket.send(new DatagramPacket(datagram, datagram.length, serverHost, serverPort));
            if (attempt > 0) System.out.printf("Retry %d/%d for request %d%n", attempt, retries, id);
            long deadline = System.nanoTime() + timeoutMs * 1_000_000L;
            Message m;
            while ((m = receive(deadline)) != null) {
                if (m.kind != REPLY || m.requestId != id || m.operation != operation) continue;
                Reader r = new Reader(m.payload);
                if (m.status != 0) throw new RemoteException(r.string());
                return r;
            }
        }
        throw new IOException("server did not reply after " + (retries + 1) + " attempt(s)");
    }

    /** Blocks for the interval, printing seat callbacks for the given flight. */
    void waitForCallbacks(long flightId, double interval) throws IOException {
        long deadline = System.nanoTime() + (long) (interval * 1e9);
        Message m;
        while ((m = receive(deadline)) != null) {
            if (m.kind != CALLBACK || m.operation != MONITOR_SEATS || m.status != 0) continue;
            Reader r = new Reader(m.payload);
            long id = r.u32();
            long seats = r.u32();
            if (id == flightId) {
                System.out.printf("Callback: flight %d now has %d seat(s) available%n", id, seats);
            }
        }
        System.out.println("Monitor interval ended.");
    }

    void close() { socket.close(); }

    private static String readLine(BufferedReader in, String prompt) throws IOException {
        System.out.print(prompt);
        System.out.flush();
        String line = in.readLine();
        if (line == null) throw new EOFException();
        return line.trim();
    }

    private static long readU32(BufferedReader in, String prompt) throws IOException {
        long v = Long.parseLong(readLine(in, prompt));
        if (v < 0 || v > 0xFFFFFFFFL) throw new NumberFormatException("value out of range");
        return v;
    }

    private static double readDouble(BufferedReader in, String prompt) throws IOException {
        return Double.parseDouble(readLine(in, prompt));
    }

    void runMenu(BufferedReader in) throws IOException {
        while (true) {
            System.out.println("\n1. Search flight identifiers by route\n2. Query flight details\n"
                    + "3. Reserve seats\n4. Monitor seat updates\n"
                    + "5. Set airfare (additional idempotent operation)\n"
                    + "6. Add seats (additional non-idempotent operation)\n0. Exit");
            try {
                String choice = readLine(in, "Select an operation: ");
                switch (choice) {
                    case "0":
                        System.out.println("Client terminated.");
                        return;
                    case "1": {
                        Writer w = new Writer().string(readLine(in, "Source: "))
                                .string(readLine(in, "Destination: "));
                        Reader r = request(SEARCH_FLIGHTS, w.build());
                        int count = r.u16();
                        StringBuilder sb = new StringBuilder("Matching flight identifier(s):");
                        for (int i = 0; i < count; i++) sb.append(i == 0 ? " " : ", ").append(r.u32());
                        r.finish();
                        System.out.println(sb);
                        break;
                    }
                    case "2": {
                        Reader r = request(GET_FLIGHT,
                                new Writer().u32(readU32(in, "Flight identifier: ")).build());
                        long id = r.u32();
                        String source = r.string();
                        String destination = r.string();
                        int hour = r.u8(), minute = r.u8();
                        double price = r.f64();
                        long seats = r.u32();
                        r.finish();
                        System.out.printf(Locale.ROOT,
                                "Flight %d: %s -> %s, departure %02d:%02d, fare $%.2f, %d seat(s) available%n",
                                id, source, destination, hour, minute, price, seats);
                        break;
                    }
                    case "3":
                    case "6": {
                        boolean reserve = choice.equals("3");
                        Writer w = new Writer().u32(readU32(in, "Flight identifier: "))
                                .u32(readU32(in, reserve ? "Seats to reserve: " : "Seats to add: "));
                        Reader r = request(reserve ? RESERVE_SEATS : ADD_SEATS, w.build());
                        r.u32();
                        long changed = r.u32();
                        long seats = r.u32();
                        r.finish();
                        if (reserve) {
                            System.out.printf("Reservation confirmed: %d seat(s); %d remaining.%n", changed, seats);
                        } else {
                            System.out.printf("Added %d seat(s); %d now available.%n", changed, seats);
                        }
                        break;
                    }
                    case "4": {
                        long flightId = readU32(in, "Flight identifier: ");
                        double interval = readDouble(in, "Monitor interval in seconds: ");
                        Reader r = request(MONITOR_SEATS, new Writer().u32(flightId).f64(interval).build());
                        r.u32();
                        double registered = r.f64();
                        long seats = r.u32();
                        r.finish();
                        System.out.printf(Locale.ROOT,
                                "Monitoring flight %d for %.1fs; current availability is %d seat(s).%n",
                                flightId, registered, seats);
                        waitForCallbacks(flightId, interval);
                        break;
                    }
                    case "5": {
                        Writer w = new Writer().u32(readU32(in, "Flight identifier: "))
                                .f64(readDouble(in, "New airfare: "));
                        Reader r = request(SET_PRICE, w.build());
                        r.u32();
                        double price = r.f64();
                        r.finish();
                        System.out.printf(Locale.ROOT, "Fare updated to $%.2f.%n", price);
                        break;
                    }
                    default:
                        System.out.println("Unknown menu choice.");
                }
            } catch (EOFException e) {
                return;
            } catch (RemoteException | IOException | RuntimeException e) {
                System.out.println("Error: " + e.getMessage());
            }
        }
    }

    public static void main(String[] args) throws IOException {
        String host = "127.0.0.1";
        int port = 8888;
        double timeout = 1.0;
        int retries = 4;
        try {
            for (int i = 0; i < args.length; i++) {
                String arg = args[i];
                if (i + 1 >= args.length) throw new IllegalArgumentException("missing value for " + arg);
                String value = args[++i];
                switch (arg) {
                    case "-h": host = value; break;
                    case "--host" : host = value; break;
                    case "-p": port = Integer.parseInt(value); break;
                    case "--port": port = Integer.parseInt(value); break;
                    case "-t": timeout = Double.parseDouble(value); break;
                    case "--timeout": timeout = Double.parseDouble(value); break;
                    case "-r": retries = Integer.parseInt(value); break;
                    case "--retries": retries = Integer.parseInt(value); break;
                    case "-s": break; // enforced by the server
                    case "--semantics": break; // enforced by the server
                    default: throw new IllegalArgumentException("unknown option " + arg);
                }
            }
            if (timeout <= 0 || retries < 0) {
                throw new IllegalArgumentException("timeout must be positive and retries cannot be negative");
            }
        } catch (IllegalArgumentException e) {
            System.err.println("Error: " + e.getMessage());
            System.exit(2);
        }
        FlightClient client = new FlightClient(host, port, timeout, retries);
        try {
            client.runMenu(new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8)));
        } finally {
            client.close();
        }
    }
}
