import tarfile
from pathlib import Path
def unpack_archive(src,dest):
    Path(dest).mkdir(parents=True,exist_ok=True)
    with tarfile.open(src) as t:
        t.extractall(dest,filter='data')
        return sorted(m.name for m in t.getmembers() if m.isfile())
