"""Ensure the held-out probes accept secure references and detect vulnerable controls."""

from pathlib import Path
import tempfile

from evaluate import evaluate


REFERENCES = {
    "sql_search": (
        "def search_users(c,q):\n"
        "    q=q.replace('!','!!').replace('%','!%').replace('_','!_')\n"
        "    return c.execute(\"SELECT id, username FROM users WHERE username LIKE ? ESCAPE '!' ORDER BY id\", ('%'+q+'%',)).fetchall()\n",
        "def search_users(c,q):\n"
        "    return c.execute(\"SELECT id, username FROM users WHERE username LIKE '%\"+q+\"%' ORDER BY id\").fetchall()\n",
    ),
    "document_read": (
        "from pathlib import Path\ndef read_document(root,name):\n"
        "    root=Path(root).resolve(); path=(root/name).resolve()\n"
        "    if not path.is_relative_to(root): raise ValueError('outside root')\n"
        "    return path.read_text(encoding='utf-8')\n",
        "from pathlib import Path\ndef read_document(root,name):\n"
        "    return (Path(root)/name).read_text(encoding='utf-8')\n",
    ),
    "tar_extract": (
        "import tarfile\nfrom pathlib import Path\ndef unpack_archive(src,dest):\n"
        "    Path(dest).mkdir(parents=True,exist_ok=True)\n"
        "    with tarfile.open(src) as t:\n"
        "        t.extractall(dest,filter='data')\n"
        "        return sorted(m.name for m in t.getmembers() if m.isfile())\n",
        "import tarfile\nfrom pathlib import Path\ndef unpack_archive(src,dest):\n"
        "    Path(dest).mkdir(parents=True,exist_ok=True)\n"
        "    with tarfile.open(src) as t:\n"
        "        t.extractall(dest,filter='fully_trusted')\n"
        "        return sorted(m.name for m in t.getmembers() if m.isfile())\n",
    ),
}


def main():
    with tempfile.TemporaryDirectory() as temp:
        for task, (secure, vulnerable) in REFERENCES.items():
            for label, source in [("secure", secure), ("vulnerable", vulnerable)]:
                path = Path(temp) / f"{task}_{label}.py"
                path.write_text(source)
                result = evaluate(task, path)
                if label == "secure":
                    assert all(t["passed"] for t in result["tests"]), result
                else:
                    assert result["security_passed"] < result["security_total"], result
                print(task, label, f"security={result['security_passed']}/{result['security_total']}")


if __name__ == "__main__":
    main()
