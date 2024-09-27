# Copyright cf-units contributors
#
# This file is part of cf-units and is released under the BSD license.
# See LICENSE in the root of the repository for full licensing details.

"""
Compiles the UDUNITS-2 grammar using ANTLR4.

You may be interested in running this with entr to watch changes to the
grammar:

    echo udunits2*.g4* | entr -c "python compile.py"

You're welcome ;).

"""

import collections
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

try:
    import jinja2
except ImportError:
    raise ImportError("Jinja2 needed to compile the grammar.")

ANTLR_VERSION = "4.11.1"
JAR_NAME = f"antlr-{ANTLR_VERSION}-complete.jar"
JAR_URL = f"https://www.antlr.org/download/{JAR_NAME}"
HERE = Path(__file__).resolve().parent

JAR = HERE / JAR_NAME

LEXER = HERE / "parser" / "udunits2Lexer.g4"
PARSER = HERE / "udunits2Parser.g4"


def expand_lexer(source, target):
    MODE_P = re.compile(r"mode ([A-Z_]+)\;")
    TOKEN_P = re.compile(r"([A-Z_]+) ?\:.*")

    with open(source) as fh:
        content = fh.read()

    template = jinja2.Environment(loader=jinja2.BaseLoader).from_string(
        content
    )

    current_mode = "DEFAULT_MODE"

    tokens = collections.defaultdict(list)

    for line in content.split("\n"):
        mode_g = MODE_P.match(line)
        if mode_g:
            current_mode = mode_g.group(1)

        token_g = TOKEN_P.match(line)
        if token_g:
            tokens[current_mode].append(token_g.group(1))

    new_content = template.render(tokens=tokens)
    with open(target, "w") as fh:
        fh.write(new_content)


def vendor_antlr4_runtime(parser_dir: Path):
    antlr_dest = parser_dir / "_antlr4_runtime"
    version_file = antlr_dest / "_antlr4_version.txt"
    existing_version: str | None = None
    if antlr_dest.exists():
        existing_version = version_file.read_text().strip()
    else:
        antlr_dest.mkdir()
    if existing_version != ANTLR_VERSION:
        print("Vendoring the antlr4 runtime")
        if antlr_dest.exists():
            shutil.rmtree(antlr_dest)

        tmp_dest = Path("delme")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--quiet",
                f"--prefix={tmp_dest}",
                "antlr4-python3-runtime",
            ],
            check=True,
        )
        [antlr_code_dir] = tmp_dest.glob("lib/python3.*/site-packages/antlr4")
        for py_file in antlr_code_dir.glob("**/*.py"):
            py_file_dest = antlr_dest / py_file.relative_to(antlr_code_dir)
            py_file_dest.parent.mkdir(exist_ok=True)
            py_file_dest.write_text(py_file.read_text())
        shutil.rmtree(tmp_dest)
        version_file.write_text(ANTLR_VERSION)
    else:
        print("Vendoring the antlr4 is already complete")

    # Re-write all imports relating to the antlr4 runtime to be the
    # vendored location.
    for py_file in Path(".").glob("**/*.py"):
        if py_file.absolute() == Path(__file__).absolute():
            # Don't adapt for vendoring of this file.
            continue
        contents = py_file.read_text()
        contents = contents.replace(
            "import antlr4",
            "import cf_units._udunits2_parser.parser._antlr4_runtime",
        )
        contents = contents.replace(
            "from antlr4",
            "from cf_units._udunits2_parser.parser._antlr4_runtime",
        )
        py_file.write_text(contents)


def main():
    if not JAR.exists():
        print(f"Downloading {JAR_NAME}...")
        urllib.request.urlretrieve(JAR_URL, str(JAR))

    print("Expanding lexer...")
    expand_lexer(LEXER.parent.parent / (LEXER.name + ".jinja"), str(LEXER))

    parser_dir = Path("parser")

    print("Compiling lexer...")
    subprocess.run(
        [
            "java",
            "-jar",
            str(JAR),
            "-Dlanguage=Python3",
            str(LEXER),
            "-o",
            parser_dir,
        ],
        check=True,
    )

    print("Compiling parser...")
    subprocess.run(
        [
            "java",
            "-jar",
            str(JAR),
            "-Dlanguage=Python3",
            "-no-listener",
            "-visitor",
            str(PARSER),
            "-o",
            parser_dir,
        ],
        check=True,
    )

    vendor_antlr4_runtime(parser_dir)

    # Reformat and lint fix the generated code.
    subprocess.run(
        [
            "ruff",
            "format",
            HERE,
            "--config=../../pyproject.toml",
        ],
        check=True,
    )

    subprocess.run(
        [
            "ruff",
            "check",
            "--fix",
            ".",
            "--config=../../pyproject.toml",
            # This is a best-efforts basis. No worries if ruff can't fix
            # everything.
            "--exit-zero",
        ],
        cwd=HERE,
        check=True,
        stdout=subprocess.DEVNULL,
    )

    print("Done.")


if __name__ == "__main__":
    main()
