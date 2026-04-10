# -*- coding: utf-8 -*-
"""설정값 로드 — 환경변수 우선, fallback: config.json"""
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"


def get_config() -> dict:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    except Exception:
        cfg = {}

    return {
        'openai_api_key': os.environ.get('OPENAI_API_KEY') or cfg.get('openai_api_key', ''),
        'simulations_per_day': int(os.environ.get('SIMULATIONS_PER_DAY', cfg.get('simulations_per_day', 5))),
        'simulation_hour': int(os.environ.get('SIMULATION_HOUR', cfg.get('simulation_hour', 9))),
        'owner_pin': os.environ.get('OWNER_PIN') or cfg.get('owner_pin', '1234'),
    }
