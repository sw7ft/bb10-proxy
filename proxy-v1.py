import http.server
import socket
import urllib.parse
import http.client
import select
import threading
import time
import sys

socket.setdefaulttimeout(30)

MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 MB
REQUEST_TIMEOUT = 60  # 60 seconds

class ConnectionPool:
    def __init__(self):
        self.pool = {}
        self.lock = threading.Lock()

    def get_connection(self, host, port=80):
        key = (host, port)
        with self.lock:
            if key not in self.pool:
                self.pool[key] = http.client.HTTPConnection(host, port, timeout=10)
            return self.pool[key]

    def close_all(self):
        with self.lock:
            for conn in self.pool.values():
                conn.close()
            self.pool.clear()

connection_pool = ConnectionPool()

class ProxyHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    def handle_one_request(self):
        try:
            self.raw_requestline = self.rfile.readline(65537)
            if len(self.raw_requestline) > 65536:
                self.requestline = ''
                self.request_version = ''
                self.command = ''
                self.send_error(414)
                return
            if not self.raw_requestline:
                self.close_connection = True
                return
            if not self.parse_request():
                return
            mname = 'do_' + self.command
            if not hasattr(self, mname):
                self.send_error(501, "Unsupported method (%r)" % self.command)
                return
            method = getattr(self, mname)
            method()
            self.wfile.flush()
        except socket.timeout as e:
            self.log_error("Request timed out: %r", e)
            self.close_connection = True
            return

    def do_CONNECT(self):
        host, port = self.path.split(":")
        port = int(port)
        conn = None

        try:
            conn = socket.create_connection((host, port), timeout=10)
            self.send_response(200, 'Connection Established')
            self.end_headers()

            self.connection.setblocking(0)
            conn.setblocking(0)

            start_time = time.time()
            while time.time() - start_time < REQUEST_TIMEOUT:
                try:
                    rlist, _, xlist = select.select([self.connection, conn], [], [self.connection, conn], 1)

                    if xlist:
                        break

                    if self.connection in rlist:
                        data_from_client = self.connection.recv(4096)
                        if data_from_client:
                            conn.sendall(data_from_client)
                        else:
                            break

                    if conn in rlist:
                        data_from_server = conn.recv(65536)
                        if data_from_server:
                            self.connection.sendall(data_from_server)
                        else:
                            break

                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.timeout) as e:
                    self.log_error("Connection error: %r", e)
                    break

        except Exception as e:
            self.send_error(502)
            self.log_error("Error in CONNECT method: %r", e)

        finally:
            if conn:
                conn.close()

    def do_GET(self):
        self.handle_request('GET')

    def do_POST(self):
        self.handle_request('POST')

    def do_HEAD(self):
        self.handle_request('HEAD')

    def handle_request(self, method):
        url = self.path
        parsed_url = urllib.parse.urlparse(url)
        netloc = parsed_url.netloc
        path = parsed_url.path if parsed_url.path else '/'
        query = parsed_url.query

        conn = connection_pool.get_connection(netloc)
        headers = self.filter_headers(self.headers)
        headers['User-Agent'] = 'Mozilla/5.0 (BB10; Touch) AppleWebKit/537.35+ (KHTML, like Gecko) Version/10.3.1.2744 Mobile Safari/537.35+'

        if query:
            path += '?' + query

        try:
            body = None
            if method == 'POST':
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length)

            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()

            content_length = int(response.getheader('Content-Length', 0))
            if content_length > MAX_CONTENT_LENGTH:
                self.send_error(413, "Content too large")
                return

            self.send_response(response.status, response.reason)
            for header, value in response.getheaders():
                self.send_header(header, value)
            self.end_headers()

            if method != 'HEAD':
                start_time = time.time()
                while time.time() - start_time < REQUEST_TIMEOUT:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()

        except (http.client.HTTPException, socket.error) as e:
            self.send_error(502)
            self.log_error("Error in %s method: %r", method, e)

        finally:
            conn.close()

    def filter_headers(self, headers):
        new_headers = {}
        for key, value in headers.items():
            if key.lower() not in ['host', 'user-agent', 'proxy-connection', 'connection']:
                new_headers[key] = value
        new_headers['Connection'] = 'close'
        return new_headers

    def log_message(self, format, *args):
        sys.stderr.write("%s - - [%s] %s\n" %
                         (self.address_string(),
                          self.log_date_time_string(),
                          format % args))

def run(server_class=http.server.ThreadingHTTPServer, handler_class=ProxyHTTPRequestHandler, port=8010):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print("Starting proxy server on port %s" % port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down the proxy server")
    finally:
        connection_pool.close_all()
        httpd.server_close()

if __name__ == '__main__':
    run()