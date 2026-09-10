import tarfile
from pathlib import Path

def unpack_archive(src, dest):
    root = Path(dest).resolve()
    root.mkdir(parents=True, exist_ok=True)
    result = []
    with tarfile.open(src) as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            relative = Path(member.name)
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('unsafe path')
            target = root / relative
            if not target.parent.resolve().is_relative_to(root):
                raise ValueError('outside root')
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open('wb') as output:
                output.write(source.read())
            result.append(relative.as_posix())
    return sorted(result)
