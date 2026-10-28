"""Retained small display fixture; this is not five-year preparation evidence."""
from viva.demo import DEMO_PASSPHRASE, demo_home, build_demo_vault, _prepare_demo_read_store
from viva.vault import Vault, holds_a_vault


def open_legacy_display_fixture(base=None):
    """Preserve the original financial scenarios independently of sample import."""
    home=demo_home(base)
    if not holds_a_vault(home):
        home.mkdir(parents=True,exist_ok=True)
        return build_demo_vault(home),True
    vault=Vault.open(home,DEMO_PASSPHRASE,create=False)
    try:
        _prepare_demo_read_store(vault)
        return vault,False
    except Exception:
        vault.close()
        raise
