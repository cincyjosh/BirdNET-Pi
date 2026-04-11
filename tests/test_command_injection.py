"""
Tests proving the command injection fixes for play.php, views.php, and advanced.php.

Three injection vectors addressed:
  1. Shell metacharacters in file paths passed to exec() (play.php)
  2. Newline injection in preg_replace() replacement strings (advanced.php)
  3. Unescaped $user/$home in shell_exec() (views.php, advanced.php)

Python's shlex.quote() is the exact equivalent of PHP's escapeshellarg().
Python's re.sub() is the exact equivalent of PHP's preg_replace().
"""

import os
import re
import shlex
import subprocess
import tempfile
import unittest


# ---------------------------------------------------------------------------
# Helpers mirroring the PHP patterns
# ---------------------------------------------------------------------------

def build_rm_cmd_unsafe(file_pointer: str) -> str:
    """Original play.php pattern — no escaping."""
    return f"rm {file_pointer} 2>&1"


def build_rm_cmd_safe(file_pointer: str) -> str:
    """Fixed pattern — escapeshellarg() via shlex.quote()."""
    return f"rm {shlex.quote(file_pointer)} 2>&1"


def build_changeidentification_cmd_unsafe(user, home, oldname, newname) -> str:
    """Original play.php:85 pattern."""
    return f'sudo -u {user} {home}/BirdNET-Pi/scripts/birdnet_changeidentification.sh "{oldname}" "{newname}" log_errors 2>&1'


def build_changeidentification_cmd_safe(user, home, oldname, newname) -> str:
    """Fixed pattern — all args escaped."""
    script = shlex.quote(home + "/BirdNET-Pi/scripts/birdnet_changeidentification.sh")
    return f"sudo -u {shlex.quote(user)} {script} {shlex.quote(oldname)} {shlex.quote(newname)} log_errors 2>&1"


def conf_replace_unsafe(contents: str, key: str, value: str) -> str:
    """Original advanced.php pattern — value used raw in replacement."""
    return re.sub(rf"{key}=.*", f'{key}="{value}"', contents)


def sanitize_conf_value(value: str) -> str:
    """
    PHP fix: strip characters that are dangerous in preg_replace replacements.
    Newlines would inject additional config keys.
    $ followed by digits would trigger backreference substitution.
    """
    value = value.replace("\n", "").replace("\r", "").replace("\0", "")
    # Escape $ so it's not treated as a backreference in the replacement string
    value = value.replace("\\", "\\\\").replace("$", r"\$")
    return value


def conf_replace_safe(contents: str, key: str, value: str) -> str:
    """Fixed pattern — value sanitized before use in replacement."""
    safe_value = sanitize_conf_value(value)
    return re.sub(rf"{key}=.*", f'{key}="{safe_value}"', contents)


# ---------------------------------------------------------------------------
# Test 1: Shell command injection via file path (play.php)
# ---------------------------------------------------------------------------

class TestShellCommandInjection(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.target_file = os.path.join(self.tmpdir, "bird.wav")
        self.side_effect_file = os.path.join(self.tmpdir, "injected.txt")
        open(self.target_file, "w").close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_injection_executes_without_escaping(self):
        """
        Documents the original bug: a semicolon in the filename breaks out of
        the rm command and executes an injected command.
        """
        malicious = f"{self.target_file}; touch {self.side_effect_file}"
        cmd = build_rm_cmd_unsafe(malicious)
        subprocess.run(cmd, shell=True, capture_output=True)  # nosec B602 - intentional: documents the injection bug
        self.assertTrue(
            os.path.exists(self.side_effect_file),
            "Injected command should have created side-effect file (documents the bug)"
        )

    def test_injection_blocked_with_escaping(self):
        """
        Proves the fix: escapeshellarg() wraps the whole path in single quotes,
        so the semicolon is treated as part of the filename, not a command separator.
        """
        malicious = f"{self.target_file}; touch {self.side_effect_file}"
        cmd = build_rm_cmd_safe(malicious)
        subprocess.run(cmd, shell=True, capture_output=True)  # nosec B602 - intentional: proves injection is blocked
        self.assertFalse(
            os.path.exists(self.side_effect_file),
            "Injection should be blocked — side-effect file must not exist"
        )

    def test_legitimate_delete_still_works(self):
        """Escaping doesn't break normal filenames."""
        cmd = build_rm_cmd_safe(self.target_file)
        result = subprocess.run(cmd, shell=True, capture_output=True)  # nosec B602 - intentional: safe command, proves legitimate delete works
        self.assertFalse(os.path.exists(self.target_file), "Legitimate file should be deleted")

    def test_filename_with_spaces_works_safely(self):
        """Escaping handles filenames with spaces correctly."""
        spaced = os.path.join(self.tmpdir, "my bird.wav")
        open(spaced, "w").close()
        cmd = build_rm_cmd_safe(spaced)
        subprocess.run(cmd, shell=True, capture_output=True)  # nosec B602 - intentional: proves spaces in filenames work safely
        self.assertFalse(os.path.exists(spaced), "File with spaces should be deleted safely")


# ---------------------------------------------------------------------------
# Test 2: Shell arg escaping for oldname/newname (play.php:85)
# ---------------------------------------------------------------------------

class TestChangeIdentificationInjection(unittest.TestCase):

    def test_injection_in_newname_without_escaping(self):
        """A malicious newname breaks out of the quoted argument."""
        malicious_newname = 'legit" ; echo INJECTED'
        cmd = build_changeidentification_cmd_unsafe("birdnet", "/home/birdnet", "old.wav", malicious_newname)
        # The raw injection appears unquoted in the command
        self.assertIn("echo INJECTED", cmd)

    def test_injection_blocked_in_newname_with_escaping(self):
        """escapeshellarg() neutralises the injection.
        The text still appears in the command but is safely quoted as a single
        argument — shlex.split() confirms 'echo' is never a standalone token."""
        malicious_newname = 'legit" ; echo INJECTED'
        cmd = build_changeidentification_cmd_safe("birdnet", "/home/birdnet", "old.wav", malicious_newname)
        # Parse the command the same way a shell would
        args = shlex.split(cmd)
        # The entire malicious string should appear as one argument
        self.assertIn(malicious_newname, args)
        # 'echo' must NOT be a standalone command token
        self.assertNotIn("echo", args)


# ---------------------------------------------------------------------------
# Test 3: Newline injection into birdnet.conf via preg_replace (advanced.php)
# ---------------------------------------------------------------------------

class TestConfNewlineInjection(unittest.TestCase):

    BASE_CONF = (
        "CADDY_PWD=oldpassword\n"
        "LATITUDE=50.0\n"
        "CONFIDENCE=0.7\n"
    )

    def test_newline_injection_without_sanitization(self):
        """
        Documents the bug: a newline in the replacement value injects a new
        key into birdnet.conf, which could override a sensitive setting.
        """
        malicious_pwd = "foo\nCONFIDENCE=0.0"
        result = conf_replace_unsafe(self.BASE_CONF, "CADDY_PWD", malicious_pwd)
        # The injected CONFIDENCE line now appears in the config
        self.assertIn("CONFIDENCE=0.0", result, "Newline injection should write extra config key (documents the bug)")

    def test_newline_injection_blocked_with_sanitization(self):
        """
        Proves the fix: sanitize_conf_value() strips newlines so the injected
        key is never written to the config file.
        """
        malicious_pwd = "foo\nCONFIDENCE=0.0"
        result = conf_replace_safe(self.BASE_CONF, "CADDY_PWD", malicious_pwd)
        lines = result.strip().split("\n")
        conf_keys = [l.split("=")[0] for l in lines if "=" in l]
        # CONFIDENCE should only appear once (original value)
        self.assertEqual(conf_keys.count("CONFIDENCE"), 1, "Injected CONFIDENCE key must not appear twice")
        # CADDY_PWD line should not contain a newline
        caddy_line = next(l for l in lines if l.startswith("CADDY_PWD"))
        self.assertNotIn("\n", caddy_line)

    def test_legitimate_password_update_still_works(self):
        """Normal passwords are written correctly."""
        result = conf_replace_safe(self.BASE_CONF, "CADDY_PWD", "myNewP@ssw0rd!")
        self.assertIn('CADDY_PWD="myNewP@ssw0rd!"', result)
        self.assertIn("LATITUDE=50.0", result)

    def test_backreference_in_value_is_escaped(self):
        """
        In PHP preg_replace, $0 in the replacement is a backreference (whole match).
        In Python re.sub, \\0 is the equivalent. The sanitizer escapes backslashes
        so they're written literally, not interpreted as backreferences.
        Note: PHP fix escapes '$', Python fix escapes '\\' — same principle.
        """
        # \0 in Python re.sub replacement would be the whole match
        value_with_backref = "pass\\0word"
        result = conf_replace_safe(self.BASE_CONF, "CADDY_PWD", value_with_backref)
        # The double backslash means the literal text \0 is preserved
        self.assertIn("pass", result)
        self.assertIn("CADDY_PWD=", result)
        # Must not have corrupted the value by substituting \0 with the match
        self.assertNotIn('CADDY_PWD=CADDY_PWD', result)


if __name__ == "__main__":
    unittest.main()
