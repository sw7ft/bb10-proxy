import http.server
import socket
import urllib.parse
import http.client
import select

class ProxyHTTPRequestHandler(http.server.BaseHTTPRequestHandler):

    def do_CONNECT(self):
        # Handle HTTPS connection (using the CONNECT method)
        host, port = self.path.split(":")
        port = int(port)
        conn = None  # Initialize conn as None

        try:
            # Create a socket connection to the destination server
            conn = socket.create_connection((host, port))

            # Send a 200 Connection established response to the client
            self.send_response(200, 'Connection Established')
            self.end_headers()

            # Forward data between client and the destination server using non-blocking I/O
            self.connection.setblocking(0)
            conn.setblocking(0)

            while True:
                try:
                    # Use select to wait for data from client or server
                    rlist, _, xlist = select.select([self.connection, conn], [], [self.connection, conn], 3)

                    if xlist:
                        break  # Close if there is an error in the connection

                    if self.connection in rlist:
                        data_from_client = self.connection.recv(102400)
                        if data_from_client:
                            conn.sendall(data_from_client)
                        else:
                            break  # Client closed connection

                    if conn in rlist:
                        data_from_server = conn.recv(102400)
                        if data_from_server:
                            self.connection.sendall(data_from_server)
                        else:
                            break  # Server closed connection

                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as e:
                    print(f"Connection error: {e}")
                    break  # Exit the loop on connection errors

        except Exception as e:
            self.send_error(502)
            print(f"Error in CONNECT method: {e}")

        finally:
            # Ensure that connections are closed properly
            if conn:
                conn.close()
            self.connection.close()

    def do_GET(self):
        # Handle regular GET requests
        url = self.path
        parsed_url = urllib.parse.urlparse(url)
        netloc = parsed_url.netloc
        path = parsed_url.path if parsed_url.path else '/'
        query = parsed_url.query

        conn = http.client.HTTPConnection(netloc)
        headers = self.filter_headers(self.headers)

        # Modify User-Agent header to appear as QNX-based browser
        headers['User-Agent'] = 'Mozilla/5.0 (BB10; Touch) AppleWebKit/537.35+ (KHTML, like Gecko) Version/10.3.1.2744 Mobile Safari/537.35+'

        if query:
            path += '?' + query

        try:
            # Send the request to the destination server
            conn.request('GET', path, headers=headers)
            response = conn.getresponse()

            # Read the entire response content
            content = response.read().decode('utf-8')

            # Inject JavaScript before the closing </body> tag
            injected_script = """
            <script>
                setTimeout(function() {
                    alert('This is an alert injected by the proxy after 5 seconds!');
                }, 5000);
            </script>
            </body>
            """
            modified_content = content.replace('</body>', injected_script)

            # Send the modified response back to the client
            self.send_response(response.status, response.reason)
            for header, value in response.getheaders():
                # Exclude 'Content-Length' since we modified the content length
                if header.lower() != 'content-length':
                    self.send_header(header, value)
            self.send_header('Content-Length', str(len(modified_content)))
            self.end_headers()

            # Send the modified content in chunks
            self.wfile.write(modified_content.encode('utf-8'))
            self.wfile.flush()  # Ensure data is sent to the client immediately

        except Exception as e:
            self.send_error(502)
            print(f"Error in GET method: {e}")

        finally:
            conn.close()

    def filter_headers(self, headers):
        # Filter out certain headers and add X-Forwarded-For with a fake IP
        new_headers = {}
        for key, value in headers.items():
            if key.lower() not in ['host', 'user-agent']:
                new_headers[key] = value
        
        # Set the X-Forwarded-For header to a fake IP address (optional)
        # new_headers['X-Forwarded-For'] = '203.0.113.195'  # Change this to the desired IP

        return new_headers

def run(server_class=http.server.HTTPServer, handler_class=ProxyHTTPRequestHandler, port=8010):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print("Starting proxy server on port", port)
    httpd.serve_forever()

if __name__ == '__main__':
    run()
