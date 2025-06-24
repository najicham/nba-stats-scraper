# --------- virtual env helpers ---------------------------------
.PHONY: venv
venv:           ## create venv ./venv and install runtime deps
	python3 -m venv venv && ./venv/bin/pip install -U pip wheel
	./venv/bin/pip install -r requirements.txt

.PHONY: dev‑venv
dev-venv: venv  ## install dev deps on top
	./venv/bin/pip install -r requirements-dev.txt

# --------- code quality ----------------------------------------
.PHONY: fmt
fmt:            ## run isort + black
	isort scrapers processors tests
	black scrapers processors tests

.PHONY: lint
lint:           ## ruff + mypy
	ruff check scrapers processors
	mypy scrapers processors

# --------- tests -----------------------------------------------
.PHONY: test
test:           ## pytest + coverage
	pytest -q --cov=scrapers --cov-report=term-missing tests/

# --------- local docker run ------------------------------------
IMAGE ?= nba-scraper
.PHONY: docker-build
docker-build:
	docker build -t $(IMAGE) .

.PHONY: scrape
scrape:         ## make scrape GAME_ID=0022400987 SCRAPER=espn_game_boxscore
	docker run --rm \
	  -e GAME_ID=$(GAME_ID) \
	  $(IMAGE) python -m scrapers.$(SCRAPER) --gameId $(GAME_ID)

help:           ## show targets
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | sort | awk 'BEGIN{FS=":.*?##"} {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
