# Copyright 2026 Xuebin Feng
# Author affiliation: University of Toronto
# SPDX-License-Identifier: Apache-2.0

"""Update VR Config's own translation catalog from opt_vr's code.

    python opt_vr/src/resources/languages/Update_Translations_VR.py           update and compile
    python opt_vr/src/resources/languages/Update_Translations_VR.py --check   change nothing; fail if stale

VR Config files its texts under the "Config" context, as the desktop Config
does. The texts the two share come from the main catalog, emapssn.ts, so
this catalog, emapssn_vr.ts, lists only the texts the main one lacks. The
update runs the main repository's Update_Translations.py on opt_vr/src,
leaving out every text emapssn.ts lists, and keeps a catalog,
emapssn_vr_<language>.ts, for each language the main catalogs have. VR
Config shows a text this catalog doesn't translate yet in English.

Run the main update first: a text VR Config shares with the desktop Config
leaves this catalog once emapssn.ts lists it.
"""

import argparse
import importlib.util
from pathlib import Path
import sys

LANGUAGES_DIR = Path(__file__).resolve().parent
VR_SRC_DIR = LANGUAGES_DIR.parents[1]
if str(VR_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(VR_SRC_DIR))

import _bootstrap_vr  # noqa: E402  (puts the parent src tree on sys.path)

MAIN_LANGUAGES_DIR = Path(_bootstrap_vr.SRC_DIR) / "resources" / "languages"
CATALOG_NAME = "emapssn_vr"


def _main_updater():
    """The main repository's Update_Translations module."""
    spec = importlib.util.spec_from_file_location(
        "Update_Translations", MAIN_LANGUAGES_DIR / "Update_Translations.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def update_vr_catalogs(
    check=False, report=print,
    source_dir=VR_SRC_DIR, languages_dir=LANGUAGES_DIR, main_languages_dir=MAIN_LANGUAGES_DIR,
):
    """Bring emapssn_vr.ts and its languages' catalogs up to date with opt_vr's code.

    With check, nothing changes, and a language the main catalogs have but
    this one lacks is a problem too. Returns 0, or 1 when something needs
    fixing; report gets every line to show.
    """
    updater = _main_updater()
    languages_dir = Path(languages_dir)
    main_languages = sorted(updater.language_catalogs(main_languages_dir))
    missing = [
        language for language in main_languages
        if not (languages_dir / f"{CATALOG_NAME}_{language}.ts").is_file()
    ]
    if check:
        for language in missing:
            report(f"{CATALOG_NAME}_{language}.ts is missing, though the main catalogs have {language}: "
                   "run the update.")
    result = updater.update_catalogs(
        source_dir=source_dir,
        languages_dir=languages_dir,
        add=() if check else main_languages,
        check=check,
        report=report,
        catalog_name=CATALOG_NAME,
        shared_template=Path(main_languages_dir) / f"{updater.CATALOG_NAME}.ts",
    )
    return 1 if result or (check and missing) else 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Update VR Config's own translation catalog from opt_vr's code, and compile it.",
    )
    parser.add_argument(
        "--check", action="store_true", help="change nothing; exit with 1 if a catalog is out of date",
    )
    arguments = parser.parse_args(argv)
    return update_vr_catalogs(check=arguments.check)


if __name__ == "__main__":
    from utilities.Output_Streams import configure_output_streams

    configure_output_streams()  # Texts may hold any character; Windows pipes can't.
    sys.exit(main())
