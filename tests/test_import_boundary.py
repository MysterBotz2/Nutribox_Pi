import importlib
import pkgutil

import nutribox_pi


def test_all_pi0_modules_import_without_raspberry_pi_packages() -> None:
    module_names = [
        module.name
        for module in pkgutil.walk_packages(
            nutribox_pi.__path__, prefix=f"{nutribox_pi.__name__}."
        )
    ]

    for module_name in module_names:
        if module_name == "nutribox_pi.__main__":
            continue
        importlib.import_module(module_name)
