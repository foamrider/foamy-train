"""Exercise the public CLI and its disk boundary with isolated XDG directories."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HELPER = Path(__file__).parents[1] / "train_fetch.py"
ROUTE = {"from": {"id": "NSR:StopPlace:1", "name": "Central"}, "to": {"id": "NSR:StopPlace:2", "name": "Airport"}}


class CliTests(unittest.TestCase):
    def test_route_is_supplied_per_request_without_config_or_state_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ, **{key: temporary + "/" + key for key in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME")})
            def run(*args, stdin=""):
                result = subprocess.run([sys.executable, str(HELPER), *args], env=env, input=stdin, capture_output=True, text=True, check=True, timeout=5)
                self.assertEqual(result.stderr, "")
                return json.loads(result.stdout)
            self.assertEqual(run("--offline")["status"], "unconfigured")
            first = run("--route-stdin", "--offline", stdin=json.dumps(ROUTE))
            self.assertEqual(first["errorCode"], "offline")
            self.assertEqual(first["route"], ROUTE)
            reverse = {"from": ROUTE["to"], "to": ROUTE["from"]}
            self.assertEqual(run("--route-stdin", "--offline", stdin=json.dumps(reverse))["route"], reverse)
            self.assertEqual(run("--route-stdin", "--offline", stdin="{}")["errorCode"], "invalid_route")
            self.assertEqual(run("--route-stdin", "--offline", stdin="{")["errorCode"], "invalid_input")
            self.assertEqual(run("--route-stdin", "--offline", stdin=json.dumps(ROUTE) + " " * 5000)["errorCode"], "invalid_route")
            self.assertEqual(run("--route-stdin", "--offline", stdin=json.dumps(ROUTE))["route"], ROUTE)
            self.assertEqual(run("--offline")["status"], "unconfigured")
            for key in ("XDG_CONFIG_HOME", "XDG_STATE_HOME"):
                self.assertFalse(Path(env[key]).exists())

    def test_search_query_starting_with_a_dash_is_not_an_option(self):
        # `--search=<text>` (as the widget passes it) keeps "-x" a query; it is too short to send.
        result = subprocess.run([sys.executable, str(HELPER), "--search=-x"], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"status": "ok", "stations": []})


if __name__ == "__main__":
    unittest.main()
