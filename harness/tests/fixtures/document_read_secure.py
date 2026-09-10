from pathlib import Path
def read_document(root,name):
    root=Path(root).resolve(); path=(root/name).resolve()
    if not path.is_relative_to(root): raise ValueError('outside root')
    return path.read_text(encoding='utf-8')
