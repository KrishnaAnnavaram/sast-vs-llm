import pytest

from sast_vs_llm.analyzers.builtin import analyze_code
from sast_vs_llm.matching import match


def rules(code):
    return {f.rule for f in analyze_code(code)}


@pytest.mark.parametrize("code,rule", [
    ("def f(x):\n    return eval(x)\n", "CWE-95"),
    ("import os\ndef f(h):\n    os.system('ping ' + h)\n", "CWE-78"),
    ("import subprocess\ndef f(c):\n    subprocess.run(c, shell=True)\n", "CWE-78"),
    ("import pickle\ndef f(b):\n    return pickle.loads(b)\n", "CWE-502"),
    ("import yaml\ndef f(t):\n    return yaml.load(t)\n", "CWE-502"),
    ("import hashlib\ndef f(p):\n    return hashlib.md5(p).hexdigest()\n", "CWE-328"),
    ("import random\ndef make_token():\n    return random.random()\n", "CWE-330"),
    ("import tempfile\ndef f():\n    return tempfile.mktemp()\n", "CWE-377"),
    ("import requests\ndef f(u):\n    return requests.get(u, verify=False)\n", "CWE-295"),
    ("def f(c, n):\n    c.execute(f'SELECT * FROM t WHERE n = {n}')\n", "CWE-89"),
    ("def f(c, n):\n    q = 'SELECT * FROM t WHERE n = %s' % n\n    c.execute(q)\n", "CWE-89"),
    ("API_KEY = 'abcdef123456'\n", "CWE-798"),
    ("import os\ndef f(name):\n    return open(os.path.join('/srv', name))\n", "CWE-22"),
    ("def delete_user(u):\n    assert u['admin']\n", "CWE-617"),
    ("def f(a=[]):\n    return a\n", "SMELL-mutable-default"),
    ("def f():\n    try:\n        pass\n    except:\n        pass\n", "SMELL-bare-except"),
    ("def f():\n    unused = 1\n    return 2\n", "SMELL-unused-variable"),
    ("def f():\n    list = [1]\n    return list\n", "SMELL-shadow-builtin"),
])
def test_rule_fires(code, rule):
    assert rule in rules(code)


@pytest.mark.parametrize("code", [
    "import subprocess\ndef f(h):\n    subprocess.run(['ping', h], check=False)\n",
    "def f(c, n):\n    c.execute('SELECT * FROM t WHERE n = ?', (n,))\n",
    "import secrets\ndef make_token():\n    return secrets.token_hex(16)\n",
    "import random\ndef shuffle_cards(cards):\n    random.shuffle(cards)\n",
    "import hashlib\ndef f(p):\n    return hashlib.sha256(p).hexdigest()\n",
    "def check(x):\n    assert x > 0\n",
    "USER_NAME = 'report_service'\n",
])
def test_safe_code_is_not_flagged(code):
    assert analyze_code(code) == []


def test_elif_chain_is_not_deep_nesting():
    branches = "\n".join(f"    elif x == {i}:\n        return {i}" for i in range(1, 8))
    code = f"def f(x):\n    if x == 0:\n        return 0\n{branches}\n"
    assert "SMELL-deep-nesting" not in rules(code)


def test_five_nested_blocks_are_flagged():
    code = "def f(a):\n    for x in a:\n        if x:\n            if x > 1:\n                if x > 2:\n                    if x > 3:\n                        return x\n"
    assert "SMELL-deep-nesting" in rules(code)


def test_builtin_on_corpus_finds_security_labels_and_no_clean_alarm(samples):
    for s in samples:
        found = analyze_code(s.code)
        if s.kind == "clean":
            assert found == [], s.id
        sec = [lab for lab in s.labels if lab.category == "security"]
        assert not match(sec, found, strict=True).fn, s.id
