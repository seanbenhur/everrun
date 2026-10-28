from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from everrun_harness import auth, providers


class AuthTests(unittest.TestCase):
    def test_fresh_oauth_access_token_does_not_need_a_refresh_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "auth.json").write_text(json.dumps({"openai": {
                "auth_type": "oauth", "access_token": "fresh-token",
                "refresh_token": "refresh-token", "expires_at": time.time() + 600,
            }}), encoding="utf-8")
            original_open = Path.open

            def deny_lock_file(path, *args, **kwargs):
                if path.name == "auth.lock":
                    raise PermissionError("refresh lock should not be needed")
                return original_open(path, *args, **kwargs)

            with patch.object(auth, "config_home", return_value=home), \
                    patch.object(providers, "config_home", return_value=home), \
                    patch.object(Path, "open", deny_lock_file):
                token = auth.openai_access_token()

        self.assertEqual(token, "fresh-token")


if __name__ == "__main__":
    unittest.main()
