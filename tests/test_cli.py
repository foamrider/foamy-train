"""The helper's command line and its disk boundary, run as a process with
isolated XDG directories against a local fake Entur (tests/fake_entur.py)."""
import json
from pathlib import Path
import unittest

from fake_entur import API_PATH, GEOCODER_PATH, ROUTE, FakeEntur, Helper, feature, temporary


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = temporary()
        self.addCleanup(self.temp.cleanup)
        self.entur = FakeEntur()
        self.addCleanup(self.entur.close)
        self.helper = Helper(self.temp.name, self.entur.url)

    def run_helper(self, *args, stdin=""):
        return self.helper.json(*args, stdin=stdin)

    def test_route_is_supplied_per_request_without_config_or_state_files(self):
        run = self.run_helper
        self.assertEqual(run("--offline")["status"], "unconfigured")
        first = run("--route-stdin", "--offline", stdin=json.dumps(ROUTE))
        self.assertEqual(first["errorCode"], "offline")
        self.assertEqual(first["route"], ROUTE)
        reverse = {"from": ROUTE["to"], "to": ROUTE["from"]}
        self.assertEqual(run("--route-stdin", "--offline", stdin=json.dumps(reverse))["route"], reverse)
        self.assertEqual(run("--route-stdin", "--offline", stdin="{}")["errorCode"], "invalid_route")
        for broken in ("{", "", "﻿", b"\xff\xfe", "null x"):
            invalid = run("--route-stdin", "--offline", stdin=broken)
            self.assertEqual((invalid["status"], invalid["route"], invalid["errorCode"], invalid["error"]),
                             ("error", None, "invalid_input", "Invalid route or unavailable local cache. Select the stations again."))
        self.assertEqual(run("--route-stdin", "--offline", stdin=json.dumps(ROUTE) + " " * 5000)["errorCode"], "invalid_route")
        self.assertEqual(run("--route-stdin", "--offline", stdin="﻿" + json.dumps(ROUTE))["route"], ROUTE)
        self.assertEqual(run("--route-stdin", "--offline", stdin=json.dumps(ROUTE))["route"], ROUTE)
        self.assertEqual(run("--offline")["status"], "unconfigured")
        for key in ("XDG_CONFIG_HOME", "XDG_STATE_HOME"):
            self.assertFalse(Path(self.helper.env[key]).exists())
        self.assertEqual(self.entur.requests, [])

    def test_search_query_starting_with_a_dash_is_not_an_option(self):
        # `--search=<text>` (as the widget passes it) keeps "-x" a query, not an option.
        self.entur.stations({"features": [feature("NSR:StopPlace:9", "-x Junction")]})
        found = self.run_helper("--search=-x")
        self.assertIn("q=-x&", self.entur.taken(GEOCODER_PATH)[0]["query"])
        self.assertEqual(found["stations"][0]["name"], "-x Junction")

    def test_search_wins_over_a_route(self):
        self.assertEqual(self.run_helper("--route-stdin", "--search=Oslo", stdin=json.dumps(ROUTE)), {"status": "ok", "stations": []})
        self.assertEqual(self.entur.taken(API_PATH), [])

    def test_argparse_forms(self):
        self.assertEqual(self.run_helper("--route", "--off", "--lang", "nb", "--hou", "2", stdin=json.dumps(ROUTE))["errorCode"], "offline")
        self.assertEqual(self.run_helper("--sea", "-5")["status"], "ok")
        self.assertEqual(self.run_helper("--search", "-x y")["status"], "ok")
        self.assertEqual(self.run_helper("--hours=7", "--hours", " 3 ", "--force", "--force", "--route-stdin",
                                         stdin=json.dumps(ROUTE))["searchHours"], 3)
        self.assertEqual([r["query"].split("&")[0] for r in self.entur.taken(GEOCODER_PATH)], ["q=-5", "q=-x+y"])

    def test_usage_errors_exit_2_without_json(self):
        bad = [["--hours", "0"], ["--hours", "25"], ["--hours", "1.5"], ["--hours="], ["--language", "de"], ["--bogus"],
               ["positional"], ["--search"], ["--search", "-x"], ["--h"], ["--force=1"], ["--", "--offline"], ["-x"]]
        for args in bad:
            with self.subTest(args=args):
                result = self.helper.run(*args)
                self.assertEqual((result.code, result.stdout), (2, b""))
                self.assertIn(b"usage:", result.stderr)
        self.assertEqual(self.entur.requests, [])

    def test_help(self):
        for flag in ("-h", "--help", "--he"):
            result = self.helper.run(flag, "--bogus")
            self.assertEqual((result.code, result.stderr), (0, b""))
            self.assertTrue(result.stdout.startswith(b"usage:"), result.stdout)


if __name__ == "__main__":
    unittest.main()
