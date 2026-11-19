""".env: where the API key goes. Parsed with the standard library, never committed."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from ews import envfile

ROOT = Path(__file__).resolve().parent.parent


class EnvFile(unittest.TestCase):
    def test_parsing(self):
        got = envfile.parse('''
# a comment
ANTHROPIC_API_KEY=sk-ant-abc123
export EWS_AGENTS=news
SEC_USER_AGENT="Tinubu EWS someone@example.com"
EMPTY=
WITH_COMMENT=200   # trailing comment
''')
        self.assertEqual(got, {"ANTHROPIC_API_KEY": "sk-ant-abc123", "EWS_AGENTS": "news",
                               "SEC_USER_AGENT": "Tinubu EWS someone@example.com",
                               "EMPTY": "", "WITH_COMMENT": "200"})

    def test_a_malformed_line_is_reported_with_its_number(self):
        with self.assertRaisesRegex(ValueError, "line 2"):
            envfile.parse("A=1\nthis is not a setting\n")

    def test_the_shell_wins_over_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("EWS_TEST_ONLY_A=from_file\nEWS_TEST_ONLY_B=from_file\n")
            os.environ["EWS_TEST_ONLY_A"] = "from_shell"
            try:
                applied = envfile.load(p)
                self.assertEqual(os.environ["EWS_TEST_ONLY_A"], "from_shell")
                self.assertEqual(os.environ["EWS_TEST_ONLY_B"], "from_file")
                self.assertEqual(applied, ["EWS_TEST_ONLY_B"])
            finally:
                os.environ.pop("EWS_TEST_ONLY_A", None)
                os.environ.pop("EWS_TEST_ONLY_B", None)

    def test_a_missing_file_is_fine(self):
        self.assertEqual(envfile.load(Path("/nonexistent/.env")), [])

    def test_the_suite_stays_on_rules_even_with_a_key_in_env(self):
        """A developer's .env must not make the tests call Claude."""
        self.assertEqual(os.environ.get("EWS_LLM"), "fallback")

    def test_env_is_never_committed_and_the_template_is(self):
        def ignored(name):
            return subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT).returncode == 0
        if not (ROOT / ".git").exists():
            self.skipTest("not a git checkout")
        self.assertTrue(ignored(".env"), ".env must be git-ignored - it holds API keys")
        self.assertFalse(ignored(".env.example"))
        self.assertIn("ANTHROPIC_API_KEY=", (ROOT / ".env.example").read_text())
