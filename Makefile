# ==============================================================
#  Python virtual‑env helpers
# ==============================================================

.PHONY: venv
venv:           ## create venv ./venv and install runtime deps
	python3 -m venv venv && ./venv/bin/pip install -U pip wheel
	./venv/bin/pip install -r requirements.txt

.PHONY: dev-venv
dev-venv: venv  ## install dev-only deps on top
	./venv/bin/pip install -r requirements-dev.txt


# ==============================================================
#  Code quality
# ==============================================================

.PHONY: fmt
fmt:            ## run isort + black
	isort scrapers processors tests
	black scrapers processors tests

.PHONY: lint
lint:           ## ruff + mypy
	ruff check scrapers processors
	mypy scrapers processors


# ==============================================================
#  Tests
# ==============================================================

.PHONY: test
test:           ## pytest + coverage
	pytest -q --cov=scrapers --cov-report=term-missing tests/


# ==============================================================
#  Local Docker build & quick run (unchanged)
# ==============================================================

IMAGE ?= nba-scraper

.PHONY: docker-build
docker-build:   ## build local image for ad‑hoc runs
	docker build -t $(IMAGE) .

.PHONY: scrape
scrape:         ## make scrape GAME_ID=0022400987 SCRAPER=espn_game_boxscore
	docker run --rm -e GAME_ID=$(GAME_ID) \
	  $(IMAGE) python -m scrapers.$(SCRAPER) --gameId $(GAME_ID)


# ==============================================================
#  ---------- Cloud Build & Cloud Run helpers -------------------
# ==============================================================

# default project / region can be overridden at command line:
# make build-image TAG=dev PROJECT=my‑proj REGION=us-west2

PROJECT ?= nba-props-platform
REGION  ?= us-west2
TAG     ?= dev

IMAGE_URI := $(REGION)-docker.pkg.dev/$(PROJECT)/pipeline/scrapers:$(TAG)

.PHONY: build-image
build-image:    ## build & push container IMAGE_URI (TAG defaults to 'dev')
	gcloud builds submit --tag "$(IMAGE_URI)" --file Dockerfile.scraper .

# ----------------------------------------------------------------
# deploy-run SERVICE=<name> MODULE=<python.module.path>
# e.g.  make deploy-run SERVICE=odds-player-props MODULE=scrapers.oddsapi.oddsa_player_props
# ----------------------------------------------------------------
.PHONY: deploy-run
deploy-run:     ## deploy Cloud Run service from last built image
ifndef SERVICE
	$(error SERVICE= required, e.g. make deploy-run SERVICE=odds-player-props MODULE=...)
endif
ifndef MODULE
	$(error MODULE= required, e.g. make deploy-run MODULE=scrapers.oddsapi.oddsa_player_props)
endif
	gcloud run deploy $(SERVICE) \
	  --image "$(IMAGE_URI)" \
	  --command python \
	  --args -m,$(MODULE) \
	  --service-account workflow-sa@$(PROJECT).iam.gserviceaccount.com \
	  --region $(REGION) \
	  --min-instances 0 --max-instances 1

# ----------------------------------------------------------------
# Workflow helpers (odds example – adjust names/files as needed)
# ----------------------------------------------------------------
.PHONY: deploy-workflow
deploy-workflow:    ## deploy odds_ingest_workflow from YAML
	gcloud workflows deploy odds_ingest_workflow \
	  --source workflows/odds_ingest.yaml \
	  --service-account workflow-sa@$(PROJECT).iam.gserviceaccount.com \
	  --location $(REGION)

.PHONY: run-workflow
run-workflow:       ## trigger odds_ingest_workflow once
	gcloud workflows run odds_ingest_workflow --project $(PROJECT)


# ==============================================================
#  Meta
# ==============================================================

.PHONY: help
help:            ## show targets and descriptions
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN{FS=":.*?##"} {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
