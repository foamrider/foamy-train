"""Runs the Python helper (train_fetch.py) for the black-box tests, with the
test-only endpoint override FOAMY_TRAIN_ENTUR_URL applied to its API and
GEOCODER constants. train_fetch.py itself has no override."""
import importlib.util
import os
from pathlib import Path

spec = importlib.util.spec_from_file_location("train_fetch", Path(__file__).resolve().parents[1] / "train_fetch.py")
train = importlib.util.module_from_spec(spec)
spec.loader.exec_module(train)
base = os.environ.get("FOAMY_TRAIN_ENTUR_URL")
if base:
    train.API = base + "/journey-planner/v3/graphql"
    train.GEOCODER = base + "/geocoder/v3/autocomplete"
train.main()
