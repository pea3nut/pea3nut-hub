#!/usr/bin/env python3
"""Exercise the real Postfix/SRS image without publishing ports or sending mail.

Run with Python 3 and a local Docker daemon. DOCKER_HOST and DOCKER are honored;
MAIL_TEST_BUILD_NETWORK may be set to 'host' for an isolated test daemon.
"""

import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = "/opt/mail-forwarder/runtime.py"
RULES = """me@pea3nut.org alice@destination.test
team@pea3nut.org bob@destination.test,carol@destination.test
"""
MESSAGE = (
    b"From: Original Sender <original@sender.test>\r\n"
    b"To: me@pea3nut.org\r\n"
    b"Subject: Signed content must stay intact\r\n"
    b"Date: Wed, 18 Nov 2026 12:00:00 +0000\r\n"
    b"Message-ID: <integration-test@sender.test>\r\n"
    b"DKIM-Signature: v=1; a=rsa-sha256; d=sender.test; s=test;\r\n"
    b" h=from:to:subject; bh=unchanged; b=unchanged\r\n"
    b"MIME-Version: 1.0\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\nHello, forwarded unchanged.\r\n.Line beginning with a dot.\r\n"
)

# This sink runs *inside* the network-isolated mail container. Only Postfix
# connects to it; it cannot deliver mail to an actual mailbox or the Internet.
SINK = r'''
import base64
import json
from pathlib import Path
import socketserver
import ssl
import threading

lock = threading.Lock()
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain("/test-certs/cert.pem", "/test-certs/key.pem")

class Handler(socketserver.StreamRequestHandler):
    def reply(self, value):
        self.wfile.write(value + b"\r\n")
        self.wfile.flush()

    def handle(self):
        sender, recipients = "", []
        self.reply(b"220 sink.test ESMTP")
        while True:
            line = self.rfile.readline()
            if not line:
                return
            command, _, argument = line.rstrip(b"\r\n").partition(b" ")
            command = command.upper()
            if command in (b"EHLO", b"HELO"):
                self.reply(b"250-sink.test")
                self.reply(b"250-STARTTLS")
                self.reply(b"250 8BITMIME")
            elif command == b"STARTTLS":
                self.reply(b"220 Ready for TLS")
                self.connection = context.wrap_socket(self.connection, server_side=True)
                self.rfile = self.connection.makefile("rb")
                self.wfile = self.connection.makefile("wb")
            elif command == b"MAIL":
                sender = argument.decode().split("<", 1)[1].split(">", 1)[0]
                recipients = []
                self.reply(b"250 Sender accepted")
            elif command == b"RCPT":
                recipients.append(argument.decode().split("<", 1)[1].split(">", 1)[0])
                self.reply(b"250 Recipient accepted")
            elif command == b"DATA":
                if Path("/tmp/sink-defer").exists():
                    self.reply(b"451 Temporary delivery failure for queue test")
                    continue
                self.reply(b"354 End with dot")
                message = bytearray()
                while True:
                    part = self.rfile.readline()
                    if part == b".\r\n":
                        break
                    if not part:
                        return
                    message.extend(part[1:] if part.startswith(b"..") else part)
                with lock, open("/tmp/sink-messages.jsonl", "a") as output:
                    output.write(json.dumps({"sender": sender, "recipients": recipients,
                        "message": base64.b64encode(message).decode()}) + "\n")
                self.reply(b"250 Stored")
            elif command == b"QUIT":
                self.reply(b"221 Bye")
                return
            elif command in (b"RSET", b"NOOP"):
                self.reply(b"250 OK")
            else:
                self.reply(b"502 Unsupported command")

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

Server(("127.0.0.1", 2525), Handler).serve_forever()
'''


class TestStack:
    def __init__(self, image, directory):
        self.image = image
        self.directory = Path(directory)
        self.name = "mail-forwarder-test-" + uuid.uuid4().hex[:12]
        self.docker = os.environ.get("DOCKER", "docker")

    def command(self, *arguments, check=True, input=None):
        result = subprocess.run([self.docker, *arguments], input=input, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if check and result.returncode:
            raise RuntimeError(f"Docker command failed: {arguments}\n{result.stdout}\n{result.stderr}")
        return result

    def execute(self, *arguments, check=True):
        return self.command("exec", self.name, *arguments, check=check)

    def python(self, code, *arguments):
        return self.execute("python3", "-c", code, *arguments).stdout.strip()

    def wait(self, predicate, label, seconds=30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                value = predicate()
                if value:
                    return value
            except (RuntimeError, ValueError):
                pass
            time.sleep(0.25)
        raise AssertionError("Timed out: " + label)

    def start(self):
        self.command("run", "-d", "--name", self.name, "--network", "none",
                     "--init", "--stop-timeout", "30",
                     "--mount", f"type=bind,src={self.directory / 'config'},dst=/etc/mail-forwarder,readonly",
                     "--mount", f"type=bind,src={self.directory / 'certs'},dst=/test-certs,readonly",
                     "--mount", f"type=bind,src={self.directory / 'queue'},dst=/var/spool/postfix",
                     "--mount", f"type=bind,src={self.directory / 'state'},dst=/var/lib/mail-forwarder",
                     "-e", "MAIL_HOSTNAME=mail.pea3nut.org",
                     "-e", "MAIL_DOMAINS=pea3nut.org",
                     "-e", "MAIL_SRS_DOMAIN=srs.pea3nut.org",
                     "-e", "MAIL_TLS_CERT_FILE=/test-certs/cert.pem",
                     "-e", "MAIL_TLS_KEY_FILE=/test-certs/key.pem", self.image)
        def ready():
            running = self.command("inspect", "--format", "{{.State.Running}}", self.name).stdout.strip()
            assert running == "true", "Mail container exited during startup"
            return self.execute("python3", RUNTIME, "healthcheck", check=False).returncode == 0
        self.wait(ready, "SMTP and SRS startup", seconds=45)

    def setup_sink(self):
        self.python("from pathlib import Path; import sys; Path('/tmp/sink.py').write_text(sys.argv[1])", SINK)
        self.command("exec", "-d", self.name, "python3", "/tmp/sink.py")
        self.wait(lambda: self.python("import socket; s=socket.create_connection(('127.0.0.1',2525),1); print(s.recv(1024).decode()); s.close()"),
                  "local TLS sink")
        self.route_to_sink()

    def route_to_sink(self):
        self.python("from pathlib import Path; Path('/etc/postfix/test_transport').write_text('destination.test smtp:[127.0.0.1]:2525\\nsender.test smtp:[127.0.0.1]:2525\\n')")
        self.execute("postmap", "hash:/etc/postfix/test_transport")
        self.execute("postconf", "-e", "transport_maps=hash:/etc/postfix/test_transport")
        self.execute("postfix", "reload")

    def reload(self):
        self.execute("python3", RUNTIME, "reload")
        # reload intentionally regenerates main.cf, so restore only the test
        # transport destination. No security or recipient policy is overridden.
        self.route_to_sink()
        time.sleep(0.25)

    def rcpt(self, recipient):
        return int(self.python("import smtplib,sys; s=smtplib.SMTP('127.0.0.1',25,timeout=5); s.ehlo('client.test'); s.mail('original@sender.test'); print(s.rcpt(sys.argv[1])[0]); s.quit()", recipient))

    def send(self, recipient="me@pea3nut.org", sender="original@sender.test", message=MESSAGE):
        self.python("import base64,smtplib,ssl,sys; s=smtplib.SMTP('127.0.0.1',25,timeout=10); s.ehlo('client.test'); assert s.has_extn('starttls'); s.starttls(context=ssl._create_unverified_context()); s.ehlo('client.test'); s.sendmail(sys.argv[1],[sys.argv[2]],base64.b64decode(sys.argv[3])); s.quit()", sender, recipient, base64.b64encode(message).decode())

    def messages(self):
        return json.loads(self.python("import json; from pathlib import Path; p=Path('/tmp/sink-messages.jsonl'); print(json.dumps([json.loads(v) for v in p.read_text().splitlines()] if p.exists() else []))"))

    def delivered(self, recipient, after=0):
        return self.wait(lambda: next((message for message in self.messages()[after:]
                                      if recipient in message["recipients"]), None),
                         "delivery to " + recipient)

    def queue(self):
        return [json.loads(line) for line in self.execute("postqueue", "-j").stdout.splitlines() if line]

    def secret_hash(self):
        return self.python("import hashlib; from pathlib import Path; print(hashlib.sha256(Path('/var/lib/mail-forwarder/postsrsd.secret').read_bytes()).hexdigest())")

    def clean(self):
        self.command("rm", "-f", self.name, check=False)
        # Docker may have created root-owned queue files even when the runner is
        # unprivileged. Remove only these two test directories through Docker.
        self.command("run", "--rm", "--network", "none", "--entrypoint", "python3",
                     "--mount", f"type=bind,src={self.directory},dst=/test-data", self.image,
                     "-c", "import shutil; shutil.rmtree('/test-data/queue', ignore_errors=True); shutil.rmtree('/test-data/state', ignore_errors=True)",
                     check=False)


def run_tests(stack):
    config = stack.directory / "config" / "forwards"
    config.write_text(RULES)
    stack.start()
    stack.setup_sink()

    assert stack.rcpt("missing@pea3nut.org") == 550, "Unknown local recipients must be rejected"
    assert stack.rcpt("victim@elsewhere.test") >= 500, "Unauthenticated external relaying must be rejected"
    assert stack.rcpt("SRS0=forged=aa=sender.test=original@srs.pea3nut.org") == 550, "Forged SRS bounces must be rejected"
    print("PASS: recipient validation, external relay denial and forged SRS rejection", flush=True)

    stack.send()
    message = stack.delivered("alice@destination.test")
    srs_address = message["sender"]
    assert srs_address.startswith(("SRS0=", "SRS0+")) and srs_address.endswith("@srs.pea3nut.org"), srs_address
    forwarded = base64.b64decode(message["message"])
    assert forwarded.split(b"\r\n\r\n", 1)[1] == MESSAGE.split(b"\r\n\r\n", 1)[1], "Body changed"
    assert b"DKIM-Signature: v=1; a=rsa-sha256; d=sender.test; s=test;\r\n h=from:to:subject; bh=unchanged; b=unchanged\r\n" in forwarded, "Original DKIM header changed"
    assert b"From: Original Sender <original@sender.test>\r\n" in forwarded, "Original From changed"
    print("PASS: STARTTLS, SRS envelope rewriting, original signed headers and body preservation", flush=True)

    before = len(stack.messages())
    stack.send("team@pea3nut.org")
    stack.delivered("bob@destination.test", before)
    stack.delivered("carol@destination.test", before)
    print("PASS: multiple forwarding destinations", flush=True)

    before = len(stack.messages())
    assert stack.rcpt(srs_address) == 250, "Valid SRS bounce address rejected"
    stack.send(srs_address, sender="", message=b"From: mailer-daemon@destination.test\r\nSubject: Test bounce\r\n\r\nDelivery failed\r\n")
    stack.delivered("original@sender.test", before)
    print("PASS: authenticated SRS bounce reversal", flush=True)

    config.write_text(RULES + "@pea3nut.org fallback@destination.test\n")
    stack.reload()
    before = len(stack.messages())
    stack.send("new-address@pea3nut.org")
    stack.delivered("fallback@destination.test", before)
    stack.send("me@pea3nut.org")
    stack.delivered("alice@destination.test", before)
    print("PASS: table reload, catch-all and exact rule precedence", flush=True)

    config.write_text("me@pea3nut.org me@pea3nut.org\n")
    result = stack.execute("python3", RUNTIME, "reload", check=False)
    assert result.returncode != 0, "Looping config must fail validation"
    before = len(stack.messages())
    stack.send()
    stack.delivered("alice@destination.test", before)
    config.write_text(RULES)
    stack.reload()
    assert stack.rcpt("new-address@pea3nut.org") == 550, "Removed catch-all still active"
    print("PASS: invalid reload preserves live rules; removed catch-all takes effect", flush=True)

    stack.wait(lambda: not stack.queue(), "empty queue before persistence test")
    secret_hash = stack.secret_hash()
    stack.python("from pathlib import Path; Path('/tmp/sink-defer').touch()")
    stack.send()
    stack.wait(lambda: any(item["queue_name"] == "deferred" for item in stack.queue()), "deferred message")
    queue_ids = {item["queue_id"] for item in stack.queue()}
    stack.command("stop", stack.name)
    stack.command("rm", stack.name)
    stack.start()
    assert stack.secret_hash() == secret_hash, "SRS secret changed across recreation"
    assert queue_ids & {item["queue_id"] for item in stack.queue()}, "Queued mail lost across recreation"
    stack.setup_sink()
    stack.execute("postqueue", "-f")
    stack.delivered("alice@destination.test")
    stack.wait(lambda: not stack.queue(), "queue drain after recovery")
    print("PASS: deferred queue and SRS secret survive container recreation; delivery retries", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="pea3nut-mail-integration")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="pea3nut-mail-integration-") as directory:
        stack = TestStack(args.image, directory)
        try:
            if not args.skip_build:
                arguments = ["build", "-t", args.image]
                if os.environ.get("MAIL_TEST_BUILD_NETWORK"):
                    arguments += ["--network", os.environ["MAIL_TEST_BUILD_NETWORK"]]
                stack.command(*arguments, str(ROOT / "mail"))
            (stack.directory / "config").mkdir()
            (stack.directory / "certs").mkdir()
            (stack.directory / "queue").mkdir()
            (stack.directory / "state").mkdir()
            stack.command("run", "--rm", "--network", "none", "--entrypoint", "openssl",
                          "--mount", f"type=bind,src={stack.directory / 'certs'},dst=/certs", args.image,
                          "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
                          "-subj", "/CN=mail.pea3nut.org", "-addext", "subjectAltName=DNS:mail.pea3nut.org",
                          "-keyout", "/certs/key.pem", "-out", "/certs/cert.pem")
            run_tests(stack)
            print("All isolated SMTP integration tests passed.", flush=True)
        except Exception:
            print(stack.command("logs", "--tail", "100", stack.name, check=False).stdout, flush=True)
            raise
        finally:
            stack.clean()


if __name__ == "__main__":
    main()
