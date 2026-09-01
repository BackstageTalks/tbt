.PHONY: test train backtest bootstrap zip

test:
	PYTHONPATH=api pytest

bootstrap:
	PYTHONPATH=api python scripts/bootstrap_history.py --start-year $${START_YEAR:-2022}

train:
	PYTHONPATH=api python scripts/train.py

backtest:
	PYTHONPATH=api python scripts/backtest.py

zip:
	cd .. && zip -r tbt-v200.zip tbt-v200 -x 'tbt-v200/.git/*' 'tbt-v200/.venv/*' 'tbt-v200/data/*' 'tbt-v200/reports/*'
