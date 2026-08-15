import socket
def main():
    client_socket=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    server_addr=('127.0.0.1',8888)

    client_socket.sendto(b"hello from client",server_addr)
    print('client has sent a "hello" message to the server')

    data,_=client_socket.recvfrom(1024)
    print(f"receive a message:{data.decode('utf_8')}")

    client_socket.close()

if __name__ == '__main__':
    main()