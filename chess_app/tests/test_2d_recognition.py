"""One registration point for the canonical recognition suite."""
import recognition_test_bootstrap


def load_tests(loader,standard_tests,pattern):
    from recognition_2d.suite import modules
    return loader.loadTestsFromNames(modules(core=False))
