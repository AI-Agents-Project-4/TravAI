"""The repo is public. Cached API responses under tests/fixtures/ must not contain API keys.

Only key-named parameters are checked (apiKey, api_key, access_token). Names like `sig=`
appear in unrelated ad links, so they are left out to avoid false alarms.
"""

import os
import re

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")
KEY_PARAM = re.compile(r"(?i)\b(api[_-]?key|access[_-]?token)=([^&\s\"'\\]+)")


def test_no_api_keys_in_cached_fixtures():
    leaks = []
    for root, _dirs, files in os.walk(FIXTURES):
        for name in files:
            path = os.path.join(root, name)
            with open(path, encoding="utf-8", errors="ignore") as f:
                text = f.read()
            for m in KEY_PARAM.finditer(text):
                if m.group(2) != "REDACTED":
                    leaks.append(f"{os.path.relpath(path, FIXTURES)}: {m.group(1)}=…")
    assert not leaks, "possible API keys in fixtures:\n" + "\n".join(leaks[:20])
