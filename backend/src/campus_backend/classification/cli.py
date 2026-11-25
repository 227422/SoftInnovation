"""Read document JSON; write public analysis or a private personal artifact."""
import argparse
import json
import sys
from pathlib import Path

from campus_backend.core.artifacts import make_artifact, read_artifact, write_artifact
from .service import PRODUCER, analyze_document, personalize
from .lifecycle import as_moment


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('document', type=Path)
    parser.add_argument('--profile', type=Path, help='Trusted local profile JSON (private output)')
    parser.add_argument('--now')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        document = read_artifact(args.document)
        now = as_moment(args.now) if args.now else None
        if args.profile is None:
            value = analyze_document(document, now=now)
        else:
            profile = json.loads(args.profile.read_text(encoding='utf-8'))
            result = personalize(document, profile, now=now)
            value = make_artifact('personal_result', document['notice_id'], document['content_version'], result,
                        producer=PRODUCER, now=now,
                        input_refs=[{'stage': 'document', 'notice_id': document['notice_id'],
                                     'content_version': document['content_version'], 'run_id': document['run_id']}])
        if args.output:
            write_artifact(args.output, value)
        else:
            print(json.dumps(value, ensure_ascii=False, indent=2))
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({'error': 'classification_input_error', 'message': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
