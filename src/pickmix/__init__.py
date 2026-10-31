'''
pickmix: entrypoint
'''

# main: launch the window, opening the config.toml given as the first argument
def main() -> None:
    import sys
    from pickmix.gui.app import run
    raise SystemExit(run(sys.argv[1:]))
