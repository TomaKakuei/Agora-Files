#!/usr/bin/env python3
"""Package both documents and their transitive TeX/figure dependencies."""
import hashlib
import re
import zipfile
from pathlib import Path

PAPER = Path(__file__).resolve().parent
STEM = 'agora_one_sentence_one_living_world_20260923'
OUTPUT = PAPER.parent / (STEM + '_tex.zip')


def main():
    files = {}
    visited = set()

    def add(relative):
        path = (PAPER / relative).resolve()
        relative = path.relative_to(PAPER)
        if not path.is_file():
            raise FileNotFoundError(path)
        files[relative.as_posix()] = path.read_bytes()
        return path

    def visit(relative):
        path = add(relative)
        if path in visited:
            return
        visited.add(path)
        source = path.read_text()
        for child in re.findall(r'\\(?:input|include)\{([^}]+)\}', source):
            visit(child if Path(child).suffix else child + '.tex')
        for graphic in re.findall(r'\\includegraphics(?:\[[^]]*\])?\{([^}]+)\}', source):
            add(graphic)
        for group in re.findall(r'\\bibliography\{([^}]+)\}', source):
            for bib in group.split(','):
                add(bib.strip() + '.bib')

    for name in (STEM, STEM + '_supplement'):
        visit(name + '.tex')
        add(name + '.pdf')
    files['build.sh'] = (PAPER / 'build_tex.sh').read_bytes()
    files['README.md'] = (PAPER / 'TEX_PACKAGE_README.md').read_bytes()
    files['SHA256SUMS.txt'] = ''.join(
        f'{hashlib.sha256(data).hexdigest()}  {name}\n'
        for name, data in sorted(files.items())
    ).encode()
    temporary = OUTPUT.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    with zipfile.ZipFile(temporary) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == set(files)
        for name, data in files.items():
            assert archive.read(name) == data, name
    temporary.replace(OUTPUT)
    print(f'{OUTPUT.name}: {len(files)} files, {OUTPUT.stat().st_size / 1024**2:.2f} MiB')


if __name__ == '__main__':
    main()
