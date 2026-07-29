import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARSE_ARGS_SCRIPT = """
import json
from run import parse_args

args = parse_args()
print(json.dumps({"bind_addr": args.bind_addr, "port": args.port}))
"""


def _parse_args(*arguments: str) -> dict:
    result = subprocess.run(
        [sys.executable, "-c", PARSE_ARGS_SCRIPT, *arguments],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    assert result.stderr == ""
    return json.loads(result.stdout)


def test_parse_args_uses_server_defaults():
    assert _parse_args() == {
        "bind_addr": "127.0.0.1",
        "port": 8080,
    }


def test_parse_args_accepts_server_overrides():
    assert _parse_args("--bind-addr", "0.0.0.0", "--port", "9090") == {
        "bind_addr": "0.0.0.0",
        "port": 9090,
    }
