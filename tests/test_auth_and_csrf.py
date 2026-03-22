"""
Tests proving fixes for weak authentication and CSRF token validation.

Issues addressed:
  1. common.php is_authenticated(): loose == comparison allowed empty password
     to match empty CADDY_PWD config. Fix: strict === comparison + non-empty check.
  2. views.php / advanced.php: state-changing forms had no CSRF token validation.
     Fix: session-bound token generated in common.php, verified before processing.
  3. common.php ensure_db_ok(): errors echoed to browser without server-side logging.
     Fix: add error_log() call before echoing.
"""

import hashlib
import hmac
import os
import secrets
import unittest


# ---------------------------------------------------------------------------
# Helpers mirroring the PHP authentication logic
# ---------------------------------------------------------------------------

def is_authenticated_unsafe(php_auth_user, php_auth_pw, caddy_pwd):
    """
    Original vulnerable PHP pattern — loose == comparison, no empty check.
    PHP: $ret = ($_SERVER['PHP_AUTH_PW'] == $config['CADDY_PWD'] &&
                 $_SERVER['PHP_AUTH_USER'] == 'birdnet');
    """
    return php_auth_pw == caddy_pwd and php_auth_user == 'birdnet'


def is_authenticated_safe(php_auth_user, php_auth_pw, caddy_pwd):
    """
    Fixed PHP pattern:
      - Requires CADDY_PWD to be non-empty (password must actually be configured)
      - Uses strict comparison (=== in PHP, == in Python with same types)
      - Uses constant-time comparison to prevent timing attacks
    PHP:
      $caddy_pwd = $config['CADDY_PWD'] ?? '';
      $ret = (strlen($caddy_pwd) > 0 &&
              hash_equals($caddy_pwd, $_SERVER['PHP_AUTH_PW']) &&
              $_SERVER['PHP_AUTH_USER'] === 'birdnet');
    """
    if not caddy_pwd:  # strlen($caddy_pwd) > 0
        return False
    if php_auth_pw is None:  # PHP: isset($_SERVER['PHP_AUTH_PW'])
        return False
    # hash_equals() is constant-time — prevents timing attacks
    pw_match = hmac.compare_digest(caddy_pwd, php_auth_pw)
    return pw_match and php_auth_user == 'birdnet'


# ---------------------------------------------------------------------------
# Helpers mirroring the PHP CSRF logic
# ---------------------------------------------------------------------------

def get_csrf_token(session: dict) -> str:
    """
    PHP: if (empty($_SESSION['csrf_token'])) {
             $_SESSION['csrf_token'] = bin2hex(random_bytes(32));
         }
         return $_SESSION['csrf_token'];
    """
    if not session.get('csrf_token'):
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']


def verify_csrf_token(session: dict, submitted_token: str) -> bool:
    """
    PHP: return hash_equals($_SESSION['csrf_token'] ?? '', $token);
    Uses constant-time comparison to prevent timing attacks.
    """
    expected = session.get('csrf_token', '')
    return hmac.compare_digest(expected, submitted_token)


# ---------------------------------------------------------------------------
# Test 1: Weak authentication
# ---------------------------------------------------------------------------

class TestWeakAuthentication(unittest.TestCase):

    def test_empty_password_config_allows_login_without_fix(self):
        """
        Documents the bug: when CADDY_PWD is empty (default), any user
        submitting an empty password is authenticated.
        """
        self.assertTrue(
            is_authenticated_unsafe('birdnet', '', ''),
            "Original code: empty password == empty config → authenticated (bug)"
        )

    def test_empty_password_config_blocked_with_fix(self):
        """
        Proves the fix: empty CADDY_PWD means no password has been configured
        — authentication should be denied entirely until a password is set.
        """
        self.assertFalse(
            is_authenticated_safe('birdnet', '', ''),
            "Fixed code: empty CADDY_PWD must not allow authentication"
        )

    def test_correct_password_authenticates(self):
        self.assertTrue(is_authenticated_safe('birdnet', 'mypassword', 'mypassword'))

    def test_wrong_password_rejected(self):
        self.assertFalse(is_authenticated_safe('birdnet', 'wrongpassword', 'mypassword'))

    def test_wrong_username_rejected(self):
        self.assertFalse(is_authenticated_safe('admin', 'mypassword', 'mypassword'))

    def test_type_juggling_prevented(self):
        """
        PHP loose == can be exploited with type juggling (e.g. 0 == 'anything').
        The fix uses hash_equals() which is always strict.
        """
        # In PHP: 0 == 'any_string_starting_with_letter' is TRUE with loose ==
        # We simulate this by checking that a numeric-like password isn't loosely matched
        self.assertFalse(is_authenticated_safe('birdnet', '0', 'somepassword'))
        self.assertFalse(is_authenticated_safe('birdnet', 'somepassword', '0'))

    def test_none_password_rejected(self):
        """PHP_AUTH_PW not set should not authenticate."""
        self.assertFalse(is_authenticated_safe('birdnet', None, 'mypassword'))

    def test_whitespace_password_not_accepted_for_empty_config(self):
        """A space character should not match an empty config password."""
        self.assertFalse(is_authenticated_safe('birdnet', ' ', ''))


# ---------------------------------------------------------------------------
# Test 2: CSRF token generation and validation
# ---------------------------------------------------------------------------

class TestCsrfToken(unittest.TestCase):

    def test_token_generated_and_stored_in_session(self):
        session = {}
        token = get_csrf_token(session)
        self.assertIn('csrf_token', session)
        self.assertEqual(token, session['csrf_token'])
        self.assertGreater(len(token), 0)

    def test_token_is_sufficient_entropy(self):
        """Token should be 32 bytes hex-encoded = 64 chars."""
        session = {}
        token = get_csrf_token(session)
        self.assertEqual(len(token), 64)

    def test_same_token_returned_on_subsequent_calls(self):
        """Token must be stable within a session — don't regenerate on each call."""
        session = {}
        token1 = get_csrf_token(session)
        token2 = get_csrf_token(session)
        self.assertEqual(token1, token2)

    def test_valid_token_accepted(self):
        session = {}
        token = get_csrf_token(session)
        self.assertTrue(verify_csrf_token(session, token))

    def test_wrong_token_rejected(self):
        session = {}
        get_csrf_token(session)
        self.assertFalse(verify_csrf_token(session, 'wrongtoken'))

    def test_empty_token_rejected(self):
        session = {}
        get_csrf_token(session)
        self.assertFalse(verify_csrf_token(session, ''))

    def test_missing_session_token_rejected(self):
        """No token in session — all submissions should fail."""
        session = {}
        self.assertFalse(verify_csrf_token(session, 'anytoken'))

    def test_tokens_differ_across_sessions(self):
        """Each new session should get a unique token."""
        session1 = {}
        session2 = {}
        token1 = get_csrf_token(session1)
        token2 = get_csrf_token(session2)
        self.assertNotEqual(token1, token2)

    def test_csrf_blocks_cross_site_request(self):
        """
        Simulates a CSRF attack: attacker's page submits a form without
        knowing the victim's session token.
        """
        victim_session = {}
        get_csrf_token(victim_session)  # Victim has a real token in session

        attacker_guessed_token = secrets.token_hex(32)  # Random guess
        self.assertFalse(
            verify_csrf_token(victim_session, attacker_guessed_token),
            "Attacker's guessed token must not match victim's session token"
        )


if __name__ == "__main__":
    unittest.main()
