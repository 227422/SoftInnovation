"""python -m campus_backend.documents.cli raw.json --assets-root DIR --output document.json"""
import argparse
from pathlib import Path

from campus_backend.core.artifacts import read_artifact, write_artifact
from .service import extract_document


def main(argv=None):
    parser = argparse.ArgumentParser(description='从原件清单独立重放正文提取')
    parser.add_argument('raw', type=Path)
    parser.add_argument('--assets-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    document = extract_document(read_artifact(args.raw), args.assets_root)
    write_artifact(args.output, document)
    return 0 if document['status'] in ('complete', 'partial') else 2


if __name__ == '__main__':
    raise SystemExit(main())
