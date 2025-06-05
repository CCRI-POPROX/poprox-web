import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

files = []
server_thread = None
PORT = 5002


def preview(html):
    global files
    global server_thread
    files.append(html)

    class RequestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Call the student-edited server code.
            index = -1
            try:
                index = int(self.path.split("/")[-1])
            except:  # noqa: E722
                print("email preview server, error parsing url", self.path)
            message = files[index]

            # Convert the return value into a byte string for network transmission
            if isinstance(message, str):
                message = bytes(message, "utf8")

            # prepare the response object with minimal viable headers.
            self.protocol_version = "HTTP/1.1"
            # Send response code
            self.send_response(200)
            # Send headers
            # Note -- this would be binary length, not string length
            self.send_header("Content-Length", len(message))
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()

            # Send the file.
            self.wfile.write(message)
            return

    def run():
        server = ("", PORT)
        httpd = HTTPServer(server, RequestHandler)
        httpd.serve_forever()

    if server_thread is None:
        server_thread = threading.Thread(target=run)
        server_thread.daemon = True
        server_thread.start()

    print(f"email preview hosted at http://localhost:{PORT}/{len(files) - 1}")
    webbrowser.open_new_tab(f"http://localhost:{PORT}/{len(files) - 1}")
