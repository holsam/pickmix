'''
pickmix: command line entry points
'''

# Import external dependencies
import argparse, os, sys
from pathlib import Path

# Import internal pickmix objects
from pickmix.lock import ProjectBusy
from pickmix.search import search

# _BAR: width of the progress bar in characters
_BAR: int = 30

# candidate_search: run template matching search from a terminal or a cluster job and print what it found; returns the exit code
def candidate_search(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog='pickmix candidate-search', description='Template match every unvisited tomogram of a project for every kind that has picks, saving the candidates for the GUI to show.')
    parser.add_argument('config', type=Path, help='the project config.toml')
    parser.add_argument('-j', '--workers', type=int, default=os.process_cpu_count() or 1, help='worker processes, one tomogram each (default: the CPUs available)')
    parser.add_argument('--threads', type=int, default=1, help='correlation threads inside each worker (default: 1)')
    parser.add_argument('-k', '--kind', action='append', dest='kinds', help='only search for this kind; repeat for several (default: all)')
    args = parser.parse_args(argv)
    if args.workers < 1 or args.threads < 1:
        parser.error('--workers and --threads must be at least 1')
    try:
        result = search(args.config, kinds=args.kinds, workers=args.workers, threads=args.threads, progress=_progress, say=_say)
    except ProjectBusy as e:
        print(e, file=sys.stderr)
        return 1
    except (ValueError, OSError) as e:
        print(f'{type(e).__name__}: {e}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('\nInterrupted, candidates found so far were saved', file=sys.stderr)
        return 130
    print(f'\nSearched {result.total} unvisited tomograms')
    for kind, summary in result.kinds.items():
        print(f'{kind}: {summary.candidates} candidates identified across {summary.tomograms} tomograms')
        if summary.skipped:
            print(f'  {len(summary.skipped)} tomograms skipped, pixel size differs from the template')
    for kind, reason in result.unusable.items():
        print(f'{kind}: no search, {reason}')
    for name, error in result.failed.items():
        print(f'{name}: failed, {error}', file=sys.stderr)
    return 1 if result.failed else 0

# _say: a stage message on stderr
def _say(message: str) -> None:
    print(message, file=sys.stderr, flush=True)

# _progress: bar redrawn in place on terminal, else one line per tomogram so a cluster log stays readable
def _progress(done: int, total: int) -> None:
    if sys.stderr.isatty():
        filled = _BAR * done // total
        print(f'\r[{"#" * filled}{"." * (_BAR - filled)}] {done}/{total}', end='', file=sys.stderr, flush=True)
    elif done:
        print(f'{done}/{total} tomograms', file=sys.stderr, flush=True)
