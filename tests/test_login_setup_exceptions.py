"""login_setup must handle the 1.5.x/1.6.0 login exceptions on the first-step login."""

import importlib.util
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from monarchmoney import CaptchaRequiredException, LoginFailedException

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("login_setup", ROOT / "login_setup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    "exc,needle",
    [
        (LoginFailedException("bad creds"), "Login failed"),
        (CaptchaRequiredException("captcha"), "CAPTCHA"),
    ],
)
@pytest.mark.asyncio
async def test_first_step_login_exceptions_are_handled(exc, needle, capsys):
    mod = _load()
    mm = MagicMock()
    mm.login = AsyncMock(side_effect=exc)
    with patch.object(mod, "MonarchMoney", return_value=mm), patch(
        "builtins.input", lambda prompt="": "user@example.test" if "Email" in prompt else "y"
    ), patch.object(mod.getpass, "getpass", return_value="pw"):
        await mod.main()
    out = capsys.readouterr().out
    assert needle in out
    assert "Testing connection" not in out  # returned before continuing
