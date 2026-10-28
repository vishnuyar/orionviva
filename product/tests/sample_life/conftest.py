"""Synthetic lifecycle tests never borrow installation-learned state."""
import pytest

@pytest.fixture(autouse=True)
def isolated_learning(monkeypatch,tmp_path):
    for key,name in [('MERCHANTCORE_HOME','merchant'),('VIVA_PROFILES','profiles'),
                     ('VIVA_CATALOG','catalog.json'),('VIVA_ENV_FILE','empty.env')]:
        monkeypatch.setenv(key,str(tmp_path/name))
    (tmp_path/'empty.env').write_text('')
