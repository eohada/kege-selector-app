import sys
import socket
import select
from fakeredis import TcpFakeServer
import fakeredis._clients._tcp_server as mod

orig_handle = mod.TCPFakeRequestHandler.handle
orig_setup = mod.TCPFakeRequestHandler.setup

def patched_handle(self):
    while not self.server._shutdown_event.is_set():
        try:
            if self.current_client.can_read():
                response = self.current_client.read_response()
                self.writer.dump(response)
                continue
            try:
                data = self.rfile.readline()
            except BlockingIOError:
                data = b""
            if data == b"":
                readable, _, _ = select.select([self.connection], [], [], 0.05)
                if not readable:
                    continue
                try:
                    data = self.rfile.readline()
                except BlockingIOError:
                    data = b""
                if data == b"":
                    try:
                        peek = self.connection.recv(1, socket.MSG_PEEK)
                        if peek == b"":
                            break
                    except Exception:
                        pass
            if data:
                self.current_client.get_socket().sendall(data)
        except ConnectionError:
            break
        except Exception:
            break

def patched_setup(self):
    orig_setup(self)
    self.connection.setblocking(False)

mod.TCPFakeRequestHandler.setup = patched_setup
mod.TCPFakeRequestHandler.handle = patched_handle


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 6379
    server = TcpFakeServer(("127.0.0.1", port))
    print(f"FakeRedis TCP server running on 127.0.0.1:{port} (Redis 8.0 protocol)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

