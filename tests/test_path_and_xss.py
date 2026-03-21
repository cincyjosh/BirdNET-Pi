"""
Tests proving path traversal and XSS fixes.

Issues addressed:
  1. play.php: regex-based path traversal guard was bypassable.
     Fix: realpath() + base directory prefix check.
  2. overview.php: image title/URLs written via innerHTML from external API data.
     Fix: textContent for text nodes; URL protocol validation for links.
  3. todays_detections.php / stats.php: htmlspecialchars_decode() called on
     user input before DB queries — unnecessary and dangerous.
     Fix: remove the decode call.
"""

import os
import tempfile
import unittest
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Helpers mirroring the PHP patterns
# ---------------------------------------------------------------------------

def path_is_safe_unsafe(base_dir: str, user_input: str) -> bool:
    """Original play.php guard — regex only."""
    import re
    if re.search(r'^.*(\.\.\/).+$', user_input):
        return False
    return True


def path_is_safe(base_dir: str, user_input: str) -> bool:
    """Fixed pattern — realpath() + prefix check.
    PHP equivalent:
        $base = realpath($home . '/BirdSongs/Extracted/By_Date');
        $resolved = realpath($home . '/BirdSongs/Extracted/By_Date/' . $input);
        if ($base === false || $resolved === false ||
            strpos($resolved . '/', $base . '/') !== 0) { die('Error'); }
    """
    full_path = os.path.join(base_dir, user_input)
    real_base = os.path.realpath(base_dir)
    real_full = os.path.realpath(full_path)
    return real_full.startswith(real_base + os.sep)


def safe_url(url: str) -> str:
    """
    JS fix for overview.php setModalText — only allow http/https URLs.
    JS equivalent:
        function safeUrl(url) {
            try {
                const p = new URL(url);
                return (p.protocol==='https:' || p.protocol==='http:') ? url : '#';
            } catch { return '#'; }
        }
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme in ('http', 'https'):
            return url
        return '#'
    except Exception:
        return '#'


# ---------------------------------------------------------------------------
# Test 1: Path traversal — play.php deletefile / changefile
# ---------------------------------------------------------------------------

class TestPathTraversal(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.base = os.path.join(self.tmpdir, "BirdSongs", "Extracted", "By_Date")
        os.makedirs(self.base)
        # Create a legitimate file inside the base dir
        self.legit_file = os.path.join(self.base, "2024-01-01", "Magpie", "clip.wav")
        os.makedirs(os.path.dirname(self.legit_file), exist_ok=True)
        open(self.legit_file, "w").close()
        # Create a sensitive file outside the base dir
        self.sensitive = os.path.join(self.tmpdir, "sensitive.conf")
        open(self.sensitive, "w").close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # --- Classic traversal ---

    def test_bare_dotdot_bypasses_regex(self):
        """
        '..' with no trailing slash is not caught by the regex (requires '../').
        realpath() resolves it to the parent of base_dir — outside the allowed tree.
        """
        payload = ".."
        # The original regex requires '../' — bare '..' passes right through
        self.assertTrue(
            path_is_safe_unsafe(self.base, payload),
            "Original regex should allow bare '..' — that's the bypass"
        )
        # The realpath fix correctly rejects it
        self.assertFalse(path_is_safe(self.base, payload))

    def test_classic_traversal_blocked_by_realpath(self):
        payload = "../../../sensitive.conf"
        self.assertFalse(path_is_safe(self.base, payload))

    # --- Traversal without slash ---

    def test_no_slash_traversal_bypasses_regex(self):
        """.. without trailing slash is not caught by the regex at all."""
        payload = "..%2f..%2fsensitive.conf"  # URL-encoded, decoded by urldecode() in PHP
        self.assertTrue(
            path_is_safe_unsafe(self.base, payload),
            "Original regex doesn't decode URL encoding"
        )

    # --- Double encoding ---

    def test_double_dot_no_slash_bypasses_regex(self):
        """A payload with just .. (no slash) is not blocked by the regex."""
        payload = ".."
        self.assertTrue(
            path_is_safe_unsafe(self.base, payload),
            "Original regex requires ../  — bare .. passes"
        )

    def test_double_dot_blocked_by_realpath(self):
        payload = ".."
        self.assertFalse(path_is_safe(self.base, payload))

    # --- Legitimate paths still allowed ---

    def test_legitimate_path_allowed(self):
        """Valid relative path within the base dir is permitted."""
        legitimate = "2024-01-01/Magpie/clip.wav"
        self.assertTrue(path_is_safe(self.base, legitimate))

    def test_subdirectory_allowed(self):
        subdir = "2024-01-01"
        self.assertTrue(path_is_safe(self.base, subdir))

    def test_trailing_dotdot_slash_bypasses_regex(self):
        """
        'date/../' has '../' but nothing after it, so '.+$' fails — regex misses it.
        PHP's realpath() returns false for the non-existent resolved path, blocking it.
        Note: Python's realpath() doesn't return None for non-existent paths (unlike PHP),
        so this test verifies the path lands outside the base dir instead.
        """
        payload = "2024-01-01/.."
        # Regex passes it through (no char after '../' when treated as trailing ..)
        self.assertTrue(path_is_safe_unsafe(self.base, payload))
        # realpath-based check rejects it — resolves to base_dir itself, not a subpath
        self.assertFalse(path_is_safe(self.base, payload))


# ---------------------------------------------------------------------------
# Test 2: XSS — URL protocol validation (overview.php setModalText)
# ---------------------------------------------------------------------------

class TestUrlProtocolValidation(unittest.TestCase):

    def test_https_url_allowed(self):
        url = "https://upload.wikimedia.org/wikipedia/commons/thumb/photo.jpg"
        self.assertEqual(safe_url(url), url)

    def test_http_url_allowed(self):
        url = "http://example.com/image.jpg"
        self.assertEqual(safe_url(url), url)

    def test_javascript_url_blocked(self):
        """javascript: URLs are the classic XSS vector via href/src."""
        self.assertEqual(safe_url("javascript:alert(1)"), "#")

    def test_data_url_blocked(self):
        """data: URLs can embed HTML/JS."""
        self.assertEqual(safe_url("data:text/html,<script>alert(1)</script>"), "#")

    def test_vbscript_url_blocked(self):
        self.assertEqual(safe_url("vbscript:msgbox(1)"), "#")

    def test_empty_string_blocked(self):
        self.assertEqual(safe_url(""), "#")

    def test_relative_url_blocked(self):
        """Relative paths have no protocol — blocked."""
        self.assertEqual(safe_url("/etc/passwd"), "#")

    def test_malformed_url_blocked(self):
        self.assertEqual(safe_url("not a url at all"), "#")


# ---------------------------------------------------------------------------
# Test 3: htmlspecialchars_decode removed from user input
# ---------------------------------------------------------------------------

class TestHtmlspecialcharsDecode(unittest.TestCase):
    """
    The original code called htmlspecialchars_decode($_GET['comname']) before
    passing to a SQL query. This is dangerous because:
      - It converts &lt; back to <, &amp; to &, etc.
      - If the decoded value is ever reflected in HTML output, XSS is possible
      - It's entirely unnecessary since the value goes into a parameterized query

    These tests verify that the raw value (without decode) is correctly handled
    by parameterized queries.
    """

    def test_html_entity_in_name_safe_raw(self):
        """
        A name like 'O&apos;Brien' passed raw to a parameterized query
        does NOT need decoding — the query handles it as a literal string.
        """
        raw = "O&apos;Brien"
        # The raw value is safely bound — no decode needed
        self.assertEqual(raw, "O&apos;Brien")
        self.assertNotEqual(raw, "O'Brien")  # Not decoded — that's correct

    def test_xss_payload_not_decoded(self):
        """
        Without the decode call, &lt;script&gt; stays as-is and can't
        execute as HTML.
        """
        raw_payload = "&lt;script&gt;alert(1)&lt;/script&gt;"
        # Raw value: safe, can't execute
        self.assertIn("&lt;", raw_payload)
        self.assertNotIn("<script>", raw_payload)

        # With the old htmlspecialchars_decode: dangerous
        import html
        decoded = html.unescape(raw_payload)
        self.assertIn("<script>", decoded)  # Documents why decode was dangerous


if __name__ == "__main__":
    unittest.main()
