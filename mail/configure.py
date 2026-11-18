"""Validate the forwarding table and generate a restricted Postfix configuration."""

from dataclasses import dataclass
import os
from pathlib import Path
import re
import ssl
import subprocess
import tempfile
import time


FORWARDS_FILE = Path("/etc/mail-forwarder/forwards")
POSTFIX_DIR = Path("/etc/postfix")
STATE_DIR = Path("/var/lib/mail-forwarder")


class ConfigurationError(ValueError):
    pass


def domain(value):
    value = value.lower()
    if len(value) > 253 or "." not in value or not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in value.split(".")
    ):
        raise ConfigurationError(f"Invalid domain name: {value!r}")
    return value


def address(value, *, catchall=False, normalize_local=False):
    if value.count("@") != 1:
        raise ConfigurationError(f"Invalid email address: {value!r}")
    local, host = value.split("@")
    host = domain(host)
    if not local and catchall:
        return "@" + host
    # Intentionally support conventional, unquoted addresses only. Postfix table
    # syntax, whitespace, pipes and control characters must never be accepted.
    if (not re.fullmatch(r"[A-Za-z0-9_+.-]{1,64}", local)
            or local.startswith(".") or local.endswith(".") or ".." in local):
        raise ConfigurationError(f"Unsupported email address: {value!r}")
    result = (local.lower() if normalize_local else local) + "@" + host
    if len(result) > 254:
        raise ConfigurationError(f"Email address is too long: {value!r}")
    return result


@dataclass(frozen=True)
class Settings:
    hostname: str
    domains: tuple
    srs_domain: str
    cert_file: str
    key_file: str

    @classmethod
    def from_environ(cls, environ=None):
        env = os.environ if environ is None else environ
        try:
            hostname = domain(env["MAIL_HOSTNAME"])
            domains = tuple(dict.fromkeys(domain(v.strip()) for v in env["MAIL_DOMAINS"].split(",")))
            srs_domain = domain(env["MAIL_SRS_DOMAIN"])
            cert_file = env["MAIL_TLS_CERT_FILE"]
            key_file = env["MAIL_TLS_KEY_FILE"]
        except KeyError as exc:
            raise ConfigurationError(f"Required environment variable missing: {exc.args[0]}") from exc
        if hostname in domains or srs_domain in domains or srs_domain == hostname:
            raise ConfigurationError("MAIL_HOSTNAME, MAIL_SRS_DOMAIN and receiving domains must be distinct")
        for value in (cert_file, key_file):
            if not re.fullmatch(r"/[A-Za-z0-9_./-]+", value) or ".." in Path(value).parts:
                raise ConfigurationError("TLS paths must be absolute paths without whitespace or '..'")
        return cls(hostname, domains, srs_domain, cert_file, key_file)


def parse_forwards(text, settings):
    rules = {}
    local_domains = {*settings.domains, settings.hostname, settings.srs_domain, "localhost"}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.partition("#")[0].strip()
        if not line:
            continue
        try:
            source_text, targets_text = line.split(None, 1)
            source = address(source_text, catchall=True, normalize_local=True)
            if source.split("@", 1)[1] not in settings.domains:
                raise ConfigurationError("Source domain is not listed in MAIL_DOMAINS")
            if source in rules:
                raise ConfigurationError(f"Duplicate source: {source}")
            targets = tuple(dict.fromkeys(address(v.strip()) for v in targets_text.split(",")))
            if any(v.split("@", 1)[1] in local_domains for v in targets):
                raise ConfigurationError("Destination must be outside all local mail domains (forwarding loop)")
            rules[source] = targets
        except ValueError as exc:
            raise ConfigurationError(f"Forwarding table line {number}: {exc}") from exc
    if not rules:
        raise ConfigurationError("Forwarding table must contain at least one rule")
    for receiving_domain in settings.domains:
        if not any(source.endswith("@" + receiving_domain) for source in rules):
            raise ConfigurationError(f"No forwarding rule configured for {receiving_domain}")
    return rules


def validate_tls(settings):
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(settings.cert_file, settings.key_file)
        subprocess.run(
            ["openssl", "x509", "-in", settings.cert_file, "-noout", "-checkend", "0"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        result = subprocess.run(
            ["openssl", "x509", "-in", settings.cert_file, "-noout", "-startdate", "-checkhost", settings.hostname],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        # OpenSSL's -checkhost reports a mismatch in stdout but may still exit 0.
        if b"does match certificate" not in result.stdout:
            raise ConfigurationError("TLS certificate does not cover MAIL_HOSTNAME")
        not_before = next(line.removeprefix("notBefore=") for line in result.stdout.decode().splitlines()
                          if line.startswith("notBefore="))
        if ssl.cert_time_to_seconds(not_before) > time.time():
            raise ConfigurationError("TLS certificate is not valid yet")
    except (OSError, ssl.SSLError, subprocess.CalledProcessError) as exc:
        raise ConfigurationError("TLS certificate/key must exist, match, be unexpired and cover MAIL_HOSTNAME") from exc


def main_cf(settings):
    return f"""# Generated by mail/configure.py; edit mail/config/forwards and mail/mail.env instead.
compatibility_level = 3.6
myhostname = {settings.hostname}
myorigin = $myhostname
inet_interfaces = all
inet_protocols = ipv4
mydestination =
mynetworks = 127.0.0.0/8
relay_domains = {settings.srs_domain}
relay_recipient_maps = tcp:127.0.0.1:10002
virtual_alias_domains = {', '.join(settings.domains)}
virtual_alias_maps = hash:/etc/postfix/virtual
alias_maps =
alias_database =
local_transport = error:Local mailbox delivery is disabled
smtpd_relay_restrictions = reject_unauth_destination
smtpd_recipient_restrictions = reject_non_fqdn_recipient, reject_unlisted_recipient
smtpd_reject_unlisted_recipient = yes
disable_vrfy_command = yes
smtpd_helo_required = yes
strict_rfc821_envelopes = yes
smtpd_sasl_auth_enable = no
smtpd_tls_security_level = may
smtpd_tls_cert_file = {settings.cert_file}
smtpd_tls_key_file = {settings.key_file}
smtpd_tls_protocols = >=TLSv1.2
smtp_tls_security_level = encrypt
smtp_tls_CAfile = /etc/ssl/certs/ca-certificates.crt
smtp_tls_protocols = >=TLSv1.2
smtp_tls_mandatory_protocols = >=TLSv1.2
smtp_tls_loglevel = 1
sender_canonical_maps = tcp:127.0.0.1:10001
sender_canonical_classes = envelope_sender
recipient_canonical_maps = tcp:127.0.0.1:10002
recipient_canonical_classes = envelope_recipient
recipient_delimiter = +
message_size_limit = 26214400
smtpd_client_connection_count_limit = 20
smtpd_client_connection_rate_limit = 60
smtpd_client_message_rate_limit = 100
smtpd_client_event_limit_exceptions =
default_process_limit = 50
maximal_queue_lifetime = 5d
bounce_queue_lifetime = 5d
maillog_file = /dev/stdout
maillog_file_prefixes = /dev/stdout
always_add_missing_headers = no
append_dot_mydomain = no
biff = no
"""


MASTER_CF = """# service type private unpriv chroot wakeup maxproc command
smtp      inet  n       -       n       -       -       smtpd
pickup    unix  n       -       n       60      1       pickup
cleanup   unix  n       -       n       -       0       cleanup
qmgr      unix  n       -       n       300     1       qmgr
tlsmgr    unix  -       -       n       1000?   1       tlsmgr
rewrite   unix  -       -       n       -       -       trivial-rewrite
bounce    unix  -       -       n       -       0       bounce
defer     unix  -       -       n       -       0       bounce
trace     unix  -       -       n       -       0       bounce
verify    unix  -       -       n       -       1       verify
flush     unix  n       -       n       1000?   0       flush
proxymap  unix  -       -       n       -       -       proxymap
proxywrite unix -       -       n       -       1       proxymap
smtp      unix  -       -       n       -       -       smtp
relay     unix  -       -       n       -       -       smtp
showq     unix  n       -       n       -       -       showq
error     unix  -       -       n       -       -       error
retry     unix  -       -       n       -       -       error
discard   unix  -       -       n       -       -       discard
anvil     unix  -       -       n       -       1       anvil
scache    unix  -       -       n       -       1       scache
postlog   unix-dgram n  -       n       -       1       postlogd
"""


def load_configuration():
    settings = Settings.from_environ()
    try:
        rules = parse_forwards(FORWARDS_FILE.read_text(encoding="utf-8"), settings)
    except OSError as exc:
        raise ConfigurationError(f"Cannot read forwarding table: {FORWARDS_FILE}") from exc
    validate_tls(settings)
    return settings, rules


def atomic_write(path, text):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(text)
    try:
        temporary.chmod(0o644)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def configure(settings, rules):
    # Build the table before replacing the live database. Invalid rules/certs are
    # rejected by load_configuration before any running configuration is changed.
    table = "".join(f"{source} {','.join(targets)}\n" for source, targets in rules.items())
    with tempfile.TemporaryDirectory(dir=POSTFIX_DIR) as temporary:
        temporary_table = Path(temporary) / "virtual"
        temporary_table.write_text(table, encoding="utf-8")
        subprocess.run(["postmap", "hash:" + str(temporary_table)], check=True)
        (Path(str(temporary_table) + ".db")).chmod(0o644)
        Path(str(temporary_table) + ".db").replace(POSTFIX_DIR / "virtual.db")
    atomic_write(POSTFIX_DIR / "virtual", table)
    atomic_write(POSTFIX_DIR / "main.cf", main_cf(settings))
    atomic_write(POSTFIX_DIR / "master.cf", MASTER_CF)
