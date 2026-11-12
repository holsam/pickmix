'''
pickmix: candidate search, template matching over unvisited tomograms in worker processes
'''

# Import external dependencies
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

# Import internal pickmix objects
from pickmix.candidates import CandidateStore
from pickmix.estimates import EstimateStore
from pickmix.lock import ProjectLock
from pickmix.match import Template, build_template, scan_tomogram, template_positions
from pickmix.model import PickStore, Progress
from pickmix.project import Project, open_project

# _SAVE_EVERY: tomograms between saves of candidates.csv, so interrupted searches keeps most of their work
_SAVE_EVERY: int = 25

# KindSummary: what a search found for one kind
@dataclass
class KindSummary:
    candidates: int = 0
    # tomograms scanned for this kind
    tomograms: int = 0
    # tomograms left out because their pixel size differs from the template's
    skipped: list[str] = field(default_factory=list)

# SearchResult: what a search did
@dataclass
class SearchResult:
    # a summary for every kind that had a template
    kinds: dict[str, KindSummary]
    # kinds that could not make a template, with the reason
    unusable: dict[str, str]
    # tomograms whose scan failed, with the error
    failed: dict[str, str]
    # tomograms searched
    total: int

# search: build a template per kind from its picks, then scan every unvisited tomogram for all of them, one tomogram per worker process
def search(
    config_path: Path, *, kinds: list[str] | None = None, workers: int = 1, threads: int = 1,
    progress: Callable[[int, int], None] = lambda done, total: None,
    say: Callable[[str], None] = lambda message: None,
) -> SearchResult:
    say(f'Reading {str(config_path)!r}')
    project = open_project(config_path)
    unknown = [k for k in kinds or [] if k not in project.config.kinds]
    if unknown:
        raise ValueError(f'unknown kinds {unknown!r}, the project has {list(project.config.kinds)!r}')
    # raises ProjectBusy when the GUI or another search has the project; the GUI would otherwise overwrite candidates.csv
    with ProjectLock(project.config.out_dir, 'candidate-search'):
        return _search(project, kinds, workers, threads, progress, say)

# _search: search tomograms with project lock
def _search(
    project: Project, kinds: list[str] | None, workers: int, threads: int,
    progress: Callable[[int, int], None], say: Callable[[str], None],
) -> SearchResult:
    config = project.config
    picks, candidates = PickStore(project), CandidateStore(project)
    estimates = EstimateStore(project, picks)
    # tomograms opened in the GUI are being picked by hand, so they are left alone
    path = config.out_dir / 'progress.json'
    visited = set(Progress.model_validate_json(path.read_text()).visited) if path.exists() else set()
    names = [n for n in project.tomos if n not in visited]
    templates: dict[str, Template] = {}
    result = SearchResult({}, {}, {}, len(names))
    for kind in kinds or list(config.kinds):
        say(f'Building template for {kind!r}')
        try:
            templates[kind] = build_template(kind, config.kinds[kind], template_positions(picks.all(kind), project.tomos, estimates), project.tomos, config)
            result.kinds[kind] = KindSummary()
        except ValueError as e:
            result.unusable[kind] = str(e)
    if not templates or not names:
        return result
    # each worker process gets its own correlation thread count
    scan_config = config.model_copy(update={'match': config.match.model_copy(update={'workers': threads})})
    say(f'Searching {len(names)} tomograms for {len(templates)} kinds with {min(workers, len(names))} workers')
    progress(0, len(names))
    pool = ProcessPoolExecutor(max_workers=min(workers, len(names)))
    try:
        futures = {pool.submit(scan_tomogram, project.tomos[n], templates, scan_config, {k: [(p.x, p.y, p.z) for p in picks.picks(n, k)] for k in templates}): n for n in names}
        for done, future in enumerate(as_completed(futures), start=1):
            name = futures[future]
            try:
                hits, skipped = future.result()
            except Exception as e:
                result.failed[name] = f'{type(e).__name__}: {e}'
            else:
                for kind, found in hits.items():
                    reach = config.match.separation * config.kinds[kind].marker_a / project.tomos[name].pixel_size
                    candidates.replace(name, kind, found, reach=reach, persist=False)
                    result.kinds[kind].tomograms += 1
                    result.kinds[kind].candidates += candidates.count(kind, name)
                for kind in skipped:
                    result.kinds[kind].skipped.append(name)
            if done % _SAVE_EVERY == 0:
                candidates.save()
            progress(done, len(names))
    except BaseException:
        # interrupt keeps what was found so far
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    finally:
        candidates.save()
    pool.shutdown()
    return result
