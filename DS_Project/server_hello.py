import socket
def main():
    server_socket=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    server_addr=('0.0.0.0',8888)
    print('server is running on the port 8888')
    server_socket.bind(server_addr)
    print(f"the server has linked to the port 8888")
    data,client_addr=server_socket.recvfrom(1024)
    print(f"server received the data from client:{data.decode('utf_8')}")
    server_socket.sendto(b"hello",client_addr)
    print('server has sent a "hello" message to the client')
    server_socket.close()

if __name__ == "__main__":
    main() 