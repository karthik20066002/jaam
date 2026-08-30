# Native CSXCAD/openEMS setup

Parsing, checking, and Python emission only require `uv sync`. `jaam run` and the
generated programs require the compiled CSXCAD and openEMS Python bindings.

On this EndeavourOS/Arch host, the available packages are:

```sh
sudo pacman -S antlr4 python-antlr4
sudo pacman -S csxcad-git openems-git python-csxcad-git python-openems-git
```

The latter two are currently provided by the configured Chaotic-AUR repository.
They build against the system Python, so native smoke tests should use that
interpreter with the JAAM source tree on `PYTHONPATH`. The uv Python 3.12
environment remains the reproducible compiler and unit-test baseline.

Verify the native bindings outside their source trees:

```sh
python3 -c 'import CSXCAD, openEMS; print(CSXCAD.__version__, openEMS.__version__)'
```

Run JAAM through the checked-in wrapper so system Python sees both the repository
source and its native system bindings:

```sh
./scripts/jaam-native run examples/yagi.jaam
```
