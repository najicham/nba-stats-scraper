```markdown
# Dockerfile Guide - *nba-props-platform*

This project ships **three container images** - one each for **scrapers**, **processors**, and **reportgen** - all built from the repository root so shared code in `config/` and `scrapers/utils/` is always present.

```

/
├─ Dockerfile.scraper      ← builds scrapers image
├─ Dockerfile.processor    ← builds processors image
├─ Dockerfile.reportgen    ← builds report-generation API
├─ .dockerignore
├─ requirements.txt              # shared libs (requests, pandas…)
├─ requirements.scrapers.txt     # extras for scrapers (proxy, bs4…)
├─ requirements.processors.txt   # extras for processors (pyarrow…)
├─ requirements.reportgen.txt    # extras for FastAPI, Jinja…
├─ scrapers/
├─ processors/
└─ reportgen/

````

---

## 1  Building

### Shared build script (already in `bin/`)
```bash
# build & push scrapers image
TAG=$(git rev-parse --short HEAD)
gcloud builds submit --tag \
  us-west2-docker.pkg.dev/$PROJECT/pipeline/scrapers:$TAG \
  --file Dockerfile.scraper .
````

Repeat with `Dockerfile.processor` and `Dockerfile.reportgen` if code in
those directories changes.

> *Tip - mutable vs. immutable tags*
> • **`dev`**: fastest iteration (overwrites)
> • **`<gitsha>` or `<YYYY-MM-DD>`**: audit-friendly prod deploys

---

## 2  Dockerfile patterns

### `Dockerfile.scraper` (multi-stage cache)

```dockerfile
########  base layer shared across *all* images  ########
FROM python:3.12-slim AS base
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

########  scrapers image  ########
FROM base as scrapers
COPY requirements.scrapers.txt .
RUN pip install --no-cache-dir -r requirements.scrapers.txt
COPY scrapers/  /app/scrapers/
COPY config/    /app/config/
CMD ["python", "-m", "scrapers.oddsapi.oddsa_player_props"]
```

`Dockerfile.processor` and `Dockerfile.reportgen`
inherit from `base` the same way but install their overlay requirements
and copy their directory.

---

## 3  `.dockerignore`

```
# never send these to the builder
.git/
__pycache__/
*.pyc
infra/
tests/
tools/
*.tfstate*
.DS_Store
```

Result: small build context, faster cache reuse.

---

## 4  Rolling out a change

| Change type                           | Which Dockerfile?        | What to do                                                           |
| ------------------------------------- | ------------------------ | -------------------------------------------------------------------- |
| Update scraping logic or shared utils | **Dockerfile.scraper**   | Re-build & push scrapers image, redeploy Cloud Run scraper services. |
| Add Parquet transform in processors   | **Dockerfile.processor** | Re-build & push processors image, redeploy processor service.        |
| Modify FastAPI templates in reportgen | **Dockerfile.reportgen** | Re-build & push reportgen image, redeploy report-gen Cloud Run.      |

*Cloud Run service names & URLs stay unchanged; only the image tag
updates.*

---

## 5  Where Terraform fits

* Terraform’s **`google_cloud_run_v2_service`** records

  * image URI
  * CPU / memory limits
  * service-account, env vars
* CI pipeline builds the new image tag, updates a `*.tfvars` file
  (`scrapers_image_tag="…:cafebabe"`) and runs `terraform apply`.

During early dev you can ignore image drift:

```hcl
lifecycle { ignore_changes = [ template[0].containers[0].image ] }
```

Terraform will leave each manual `gcloud run deploy` alone until
you are ready for pinned tags.

---

## 6  Debug tips

* **Run locally**

  ```bash
  docker run --rm -e DEBUG=1 \
    us-west2-docker.pkg.dev/$PROJECT/pipeline/scrapers:dev \
    python -m scrapers.oddsapi.oddsa_events_his --date 2024-02-14
  ```
* **Inspect layers**

  ```bash
  docker history us-west2-docker.pkg.dev/...:dev
  ```
* **Size bloat** → check `.dockerignore` and avoid installing build tools inside slim image.

Keep this guide handy; the directory-per-Dockerfile pattern stays simple yet scales as each component matures. 🌟

```
```
