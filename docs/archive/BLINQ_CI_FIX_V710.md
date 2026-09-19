# BlinQ v7.1.0 CI fix

- CI now runs only canonical tests under `tests/`.
- Accidental root-level `test_*.py` duplicates are ignored by Git and are not present in this clean archive.
- This prevents duplicate-module collection errors and broken relative paths caused by files such as `test_foo (2).py`.
- Frontend/login/runtime code is unchanged from v7.0.9.
