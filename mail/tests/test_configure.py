from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from configure import ConfigurationError, Settings, parse_forwards, validate_tls


class ForwardingConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "MAIL_HOSTNAME": "mail.example.org",
            "MAIL_DOMAINS": "example.org,example.net",
            "MAIL_SRS_DOMAIN": "srs.example.org",
            "MAIL_TLS_CERT_FILE": "/certs/fullchain.pem",
            "MAIL_TLS_KEY_FILE": "/certs/privkey.pem",
        }
        self.settings = Settings.from_environ(self.env)

    def parse(self, rule):
        # A served domain must not silently have an empty forwarding table.
        return parse_forwards(rule + "\nme@example.net other@gmail.com\n", self.settings)

    def test_exact_catchall_and_multiple_destinations(self):
        rules = self.parse("""
            # A comment
            ME@EXAMPLE.ORG person@Gmail.com,other@qq.com,person@gmail.com # duplicate target
            @example.org catchall@outlook.com
        """)
        self.assertEqual(rules["me@example.org"], ("person@gmail.com", "other@qq.com"))
        self.assertEqual(rules["@example.org"], ("catchall@outlook.com",))

    def test_destination_localpart_preserves_case(self):
        rules = self.parse("me@example.org Mixed.Case@EXAMPLE.COM")
        self.assertEqual(rules["me@example.org"], ("Mixed.Case@example.com",))

    def test_reject_duplicate_source_even_with_case_variations(self):
        with self.assertRaisesRegex(ConfigurationError, "line 2.*Duplicate"):
            self.parse("Me@example.org first@gmail.com\nme@EXAMPLE.ORG second@gmail.com")

    def test_reject_any_destination_in_local_domains(self):
        for target in ("other@example.org", "other@example.net", "user@mail.example.org", "user@srs.example.org"):
            with self.subTest(target=target), self.assertRaisesRegex(ConfigurationError, "forwarding loop"):
                self.parse("me@example.org " + target)

    def test_reject_source_outside_served_domains(self):
        with self.assertRaisesRegex(ConfigurationError, "not listed"):
            self.parse("me@example.com someone@gmail.com")

    def test_reject_unsafe_or_malformed_destinations(self):
        for target in ("|command", "/etc/passwd", '"name"@gmail.com', "a@gmail.com b@qq.com",
                       "a@gmail.com,", ",a@gmail.com", "a@localhost", "a@-gmail.com", "a..b@gmail.com",
                       "a@gmail.com\x00", "a@gmail.com\x1b", "a@gmail.com\rmalicious=value"):
            with self.subTest(target=repr(target)), self.assertRaises(ConfigurationError):
                self.parse("me@example.org " + target)

    def test_reject_malformed_sources(self):
        for source in ("*", "*@example.org", "me", "a@@example.org", ".me@example.org"):
            with self.subTest(source=source), self.assertRaises(ConfigurationError):
                self.parse(source + " someone@gmail.com")

    def test_reject_empty_table_or_unconfigured_domain(self):
        for text in ("", "# comments only", "me@example.org someone@gmail.com"):
            with self.subTest(text=text), self.assertRaises(ConfigurationError):
                parse_forwards(text, self.settings)

    def test_domains_are_deduplicated(self):
        self.env["MAIL_DOMAINS"] = "EXAMPLE.ORG, example.org"
        self.assertEqual(Settings.from_environ(self.env).domains, ("example.org",))

    def test_reject_invalid_environment(self):
        for name, value in (
            ("MAIL_DOMAINS", "example.org,"),
            ("MAIL_HOSTNAME", "mail.example.org\nrelayhost=attacker"),
            ("MAIL_HOSTNAME", "example.org"),
            ("MAIL_SRS_DOMAIN", "example.net"),
            ("MAIL_SRS_DOMAIN", "mail.example.org"),
            ("MAIL_TLS_CERT_FILE", "/certs/a.pem\nrelayhost=attacker"),
            ("MAIL_TLS_KEY_FILE", "relative.pem"),
            ("MAIL_TLS_KEY_FILE", "/certs/../secret.pem"),
        ):
            env = {**self.env, name: value}
            with self.subTest(name=name, value=value), self.assertRaises(ConfigurationError):
                Settings.from_environ(env)


class CertificateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.cert = str(Path(cls.temporary.name) / "cert.pem")
        cls.key = str(Path(cls.temporary.name) / "key.pem")
        cls.wrong_key = str(Path(cls.temporary.name) / "wrong-key.pem")
        cls.expired_cert = str(Path(cls.temporary.name) / "expired-cert.pem")
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=mail.example.org", "-addext", "subjectAltName=DNS:mail.example.org",
            "-keyout", cls.key, "-out", cls.cert,
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([
            "openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", cls.wrong_key,
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([
            "openssl", "x509", "-in", cls.cert, "-signkey", cls.key, "-days", "0", "-out", cls.expired_cert,
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def settings(self, hostname="mail.example.org", key=None):
        return Settings(hostname, ("example.org",), "srs.example.org", self.cert, key or self.key)

    def test_valid_certificate(self):
        validate_tls(self.settings())

    def test_wrong_hostname(self):
        with self.assertRaises(ConfigurationError):
            validate_tls(self.settings(hostname="attacker.example.org"))

    def test_missing_key(self):
        with self.assertRaises(ConfigurationError):
            validate_tls(self.settings(key="/nonexistent/key.pem"))

    def test_mismatched_key(self):
        with self.assertRaises(ConfigurationError):
            validate_tls(self.settings(key=self.wrong_key))

    def test_expired_certificate(self):
        expired = Settings("mail.example.org", ("example.org",), "srs.example.org", self.expired_cert, self.key)
        with self.assertRaises(ConfigurationError):
            validate_tls(expired)


if __name__ == "__main__":
    unittest.main()
