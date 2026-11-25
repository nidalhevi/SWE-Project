"""One-shot board localization, separate from Qt and piece recognition."""
import json
from pathlib import Path
import sys


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True)
    args = parser.parse_args(argv)
    try:
        request = json.loads(args.request)
        if type(request.get('request_id')) is not int or request['request_id'] < 0:
            raise ValueError('Invalid request ID')
        from lichess_2d.board_locator_2d import load_image
        from lichess_2d.board_proposals import propose_boards, proposal_document
        with load_image(request['path']) as image:
            proposals = propose_boards(image)
        print(json.dumps(proposal_document(proposals, request['request_id']), allow_nan=False), flush=True)
        return 0
    except Exception as error:
        print('Board search failed: ' + str(error), file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.exit(main())
