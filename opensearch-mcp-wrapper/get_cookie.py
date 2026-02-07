#!/usr/bin/env python3
"""
Helper script to extract OpenSearch session cookie from browser.

Usage:
    python get_cookie.py [browser] [domain]

Examples:
    python get_cookie.py chrome opensearch-dashboard.e1-us-east-azure.example.com
    python get_cookie.py firefox opensearch-dashboard.e1-us-east-azure.example.com
"""

import sys
import subprocess
import json


def get_chrome_cookies_macos(domain: str) -> str:
    """Extract cookies from Chrome on macOS using sqlite3."""
    import sqlite3
    import os
    import shutil
    import tempfile

    # Chrome stores cookies in this location on macOS
    cookie_path = os.path.expanduser(
        "~/Library/Application Support/Google/Chrome/Default/Cookies"
    )

    if not os.path.exists(cookie_path):
        print(f"Chrome cookie database not found at: {cookie_path}", file=sys.stderr)
        return ""

    # Copy to temp file since Chrome locks the database
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
        tmp_path = tmp.name

    try:
        shutil.copy2(cookie_path, tmp_path)
        conn = sqlite3.connect(tmp_path)
        cursor = conn.cursor()

        # Query cookies for the domain
        cursor.execute(
            """
            SELECT name, value, encrypted_value
            FROM cookies
            WHERE host_key LIKE ?
            """,
            (f"%{domain}%",),
        )

        cookies = []
        for name, value, encrypted_value in cursor.fetchall():
            if value:
                cookies.append(f"{name}={value}")
            elif encrypted_value:
                # Encrypted cookies need keychain access - skip for now
                print(f"Note: Cookie '{name}' is encrypted. You may need to export manually.", file=sys.stderr)

        conn.close()
        return "; ".join(cookies)

    finally:
        os.unlink(tmp_path)


def print_manual_instructions(domain: str):
    """Print instructions for manual cookie extraction."""
    print("""
=== Manual Cookie Extraction Instructions ===

Since automated extraction may not work (encrypted cookies), follow these steps:

1. Open your browser and go to your OpenSearch Dashboard
2. Make sure you're logged in
3. Open Developer Tools (F12 or Cmd+Option+I)
4. Go to: Application tab → Cookies → your domain
5. Find cookies that look like:
   - security_authentication_oidc
   - security_authentication
   - Or any cookie starting with 'security_'

6. Copy the cookie(s) in this format:
   cookie_name=cookie_value; another_cookie=another_value

7. Set the environment variable:
   export OPENSEARCH_COOKIE="security_authentication_oidc=YOUR_VALUE_HERE"

=== Alternative: Export from DevTools Console ===

In the browser console (while on your OpenSearch page), run:
   document.cookie

Copy the output and use it as OPENSEARCH_COOKIE value.

=== For your domain ===
""")
    print(f"Domain: {domain}")
    print(f'\nexport OPENSEARCH_URL="https://{domain}"')
    print('export OPENSEARCH_COOKIE="<paste your cookie here>"')


def main():
    browser = sys.argv[1] if len(sys.argv) > 1 else "chrome"
    domain = sys.argv[2] if len(sys.argv) > 2 else "opensearch-dashboard.e1-us-east-azure.example.com"

    print(f"Attempting to extract cookies for: {domain}", file=sys.stderr)

    if browser == "chrome" and sys.platform == "darwin":
        cookies = get_chrome_cookies_macos(domain)
        if cookies:
            print(f"\nFound cookies:\n{cookies}\n")
            print(f'\nexport OPENSEARCH_COOKIE="{cookies}"')
        else:
            print_manual_instructions(domain)
    else:
        print_manual_instructions(domain)


if __name__ == "__main__":
    main()
