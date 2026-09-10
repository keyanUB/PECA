from pathlib import Path
def read_document(root,name):
    return (Path(root)/name).read_text(encoding='utf-8')
