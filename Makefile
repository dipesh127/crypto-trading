test:
	PYTHONPATH=. pytest -q
compile:
	python -m py_compile $$(find app scripts -name "*.py")
db-explain:
	python scripts/verify_dashboard_indexes.py --json
frontend-build:
	cd frontend && npm ci && npm run build
