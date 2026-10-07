import shutil

import pytest

from sast_vs_llm.corpus import default_corpus_dir, load_corpus


@pytest.fixture(scope="session")
def samples():
    return load_corpus()


@pytest.fixture(scope="session")
def by_id(samples):
    return {s.id: s for s in samples}


@pytest.fixture()
def corpus_copy(tmp_path):
    dst = tmp_path / "corpus"
    shutil.copytree(default_corpus_dir(), dst)
    return dst
