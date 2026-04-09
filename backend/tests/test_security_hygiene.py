import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_PATHS = (
    REPO_ROOT / "backend" / "app",
    REPO_ROOT / "backend" / "app" / "frontend",
    REPO_ROOT / "js",
    REPO_ROOT / "account.html",
    REPO_ROOT / "admin.html",
    REPO_ROOT / "booking.html",
    REPO_ROOT / "bookings.html",
    REPO_ROOT / "contact.html",
    REPO_ROOT / "faq.html",
    REPO_ROOT / "index.html",
    REPO_ROOT / "info.html",
    REPO_ROOT / "reserve.html",
    REPO_ROOT / "room.html",
    REPO_ROOT / "rooms.html",
    REPO_ROOT / "staff.html",
)
TEXT_FILE_EXTENSIONS = {".py", ".js", ".html", ".css"}
SECRET_PATTERNS = (
    re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\brk_(?:live|test)_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bpk_live_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bwhsec_[A-Za-z0-9]{20,}\b"),
)
PUBLIC_IP_PATTERN = re.compile(r"\b(?!(?:10|127)\.\d{1,3}\.\d{1,3}\.\d{1,3})(?!(?:172\.(?:1[6-9]|2\d|3[0-1]))\.\d{1,3}\.\d{1,3})(?!(?:192\.168)\.\d{1,3}\.\d{1,3})(?!(?:0\.0\.0\.0)\b)(\d{1,3}(?:\.\d{1,3}){3})\b")


def _iter_files():
    for path in SCAN_PATHS:
        if path.is_file():
            yield path
            continue
        for child in path.rglob("*"):
            if child.is_file() and child.suffix in TEXT_FILE_EXTENSIONS:
                yield child


class SecurityHygieneTest(unittest.TestCase):
    def test_app_source_does_not_contain_real_hardcoded_secret_tokens(self) -> None:
        findings = []
        for path in _iter_files():
            content = path.read_text(encoding="utf-8")
            for pattern in SECRET_PATTERNS:
                for match in pattern.finditer(content):
                    findings.append(f"{path.relative_to(REPO_ROOT)}:{match.group(0)[:12]}...")
        self.assertEqual(findings, [])

    def test_app_source_does_not_contain_public_ipv4_literals(self) -> None:
        findings = []
        for path in _iter_files():
            content = path.read_text(encoding="utf-8")
            for match in PUBLIC_IP_PATTERN.finditer(content):
                findings.append(f"{path.relative_to(REPO_ROOT)}:{match.group(1)}")
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
