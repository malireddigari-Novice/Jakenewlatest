"""
Two-step Schwab OAuth helper (browser step done by the user; token exchange done here).

  python schwab_get_token.py url
      → prints the Schwab authorization URL and saves the auth context (state) to a temp file.
        Open the URL, log into Schwab, approve; your browser redirects to the (dead) callback URL.

  python schwab_get_token.py exchange "<full redirected URL from the address bar>"
      → exchanges the one-time code for a token and writes it to SCHWAB_TOKEN_FILE in the exact
        format schwab-py's client_from_token_file expects.

Unlike schwab_reauth.py's single-process manual flow, this splits URL-generation and token-exchange
so the two can happen in separate invocations (the AuthContext state is persisted between them).
"""
import json
import os
import sys

import config
import schwab.auth

CTX_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.schwab_auth_ctx.json')


def cmd_url():
    ctx = schwab.auth.get_auth_context(config.SCHWAB_API_KEY, config.SCHWAB_CALLBACK_URL)
    with open(CTX_FILE, 'w') as f:
        json.dump({'callback_url': ctx.callback_url,
                   'authorization_url': ctx.authorization_url,
                   'state': ctx.state}, f)
    print(ctx.authorization_url)


def cmd_exchange(received_url):
    with open(CTX_FILE) as f:
        d = json.load(f)
    ctx = schwab.auth.AuthContext(d['callback_url'], d['authorization_url'], d['state'])

    def writer(t, *args, **kwargs):
        with open(config.SCHWAB_TOKEN_FILE, 'w') as f:
            json.dump(t, f)

    schwab.auth.client_from_received_url(
        config.SCHWAB_API_KEY, config.SCHWAB_APP_SECRET, ctx, received_url, writer)
    try:
        os.remove(CTX_FILE)
    except OSError:
        pass
    print(f"TOKEN SAVED to {config.SCHWAB_TOKEN_FILE}")


def _unextract_truststore():
    # pip-system-certs (pip_system_certs.pth) globally injects truststore into ssl.SSLContext.wrap_socket
    # at startup; truststore only supports CLIENT sockets, so an HTTPS callback SERVER crashes on
    # get_unverified_chain(). Un-inject it in THIS process so our server can wrap its socket; the
    # client-side token exchange then uses the default (certifi) store, which validates Schwab's cert.
    for _mod in ('truststore', 'pip._vendor.truststore'):
        try:
            __import__(_mod, fromlist=['extract_from_ssl']).extract_from_ssl()
        except Exception:
            pass


def cmd_login():
    """Single-process local-server flow: open the browser, capture the redirect on the callback URL,
    and exchange the code the instant it arrives — no manual paste, so the ~30s code TTL never expires.
    Runs the server in THIS process (not schwab-py's spawned child, which would re-inject truststore and
    crash). Browser warns about the self-signed cert on 127.0.0.1 — click through (Advanced → Proceed)."""
    import http.server
    import ssl
    import urllib.parse
    import webbrowser
    from werkzeug.serving import generate_adhoc_ssl_context

    _unextract_truststore()
    ctx = schwab.auth.get_auth_context(config.SCHWAB_API_KEY, config.SCHWAB_CALLBACK_URL)
    parsed = urllib.parse.urlparse(config.SCHWAB_CALLBACK_URL)
    host, port = parsed.hostname, (parsed.port or 443)
    captured = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(q)
            if 'code' in params:
                captured['url'] = config.SCHWAB_CALLBACK_URL.rstrip('/') + self.path
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<h2>Schwab login received. You can close this tab.</h2>")

        def log_message(self, *a):
            pass

    httpd = http.server.HTTPServer((host, port), Handler)
    httpd.socket = generate_adhoc_ssl_context().wrap_socket(httpd.socket, server_side=True)
    print(f"listening on {config.SCHWAB_CALLBACK_URL} — opening browser, log in and approve ...",
          flush=True)
    webbrowser.open(ctx.authorization_url)
    print("if no browser opened, paste this URL manually:\n  " + ctx.authorization_url, flush=True)

    def writer(t, *args, **kwargs):
        with open(config.SCHWAB_TOKEN_FILE, 'w') as f:
            json.dump(t, f)

    # Keep listening until an exchange SUCCEEDS. A stale/duplicate hit that fails to exchange must NOT
    # kill the server — clear it and wait for the browser to deliver a fresh code. (Each Schwab code is
    # single-use and short-lived, so only the first valid delivery wins; everything else is discarded.)
    httpd.timeout = 300
    while True:
        captured.pop('url', None)
        while 'url' not in captured:
            httpd.handle_request()
        try:
            schwab.auth.client_from_received_url(
                config.SCHWAB_API_KEY, config.SCHWAB_APP_SECRET, ctx, captured['url'], writer)
            print(f"TOKEN SAVED to {config.SCHWAB_TOKEN_FILE}", flush=True)
            return
        except Exception as exc:
            print(f"exchange failed ({exc}); still listening — approve again in the browser ...",
                  flush=True)


if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in ('url', 'exchange', 'login'):
        print(__doc__); sys.exit(1)
    if sys.argv[1] == 'url':
        cmd_url()
    elif sys.argv[1] == 'login':
        cmd_login()
    else:
        if len(sys.argv) < 3:
            print("Paste the full redirected URL in quotes."); sys.exit(1)
        cmd_exchange(sys.argv[2])
