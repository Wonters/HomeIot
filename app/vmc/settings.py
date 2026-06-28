from config_store import get_macro

VMC_MACRO_KEY = "vmc"


def get_vmc_config() -> dict:
    return get_macro(VMC_MACRO_KEY, {})
