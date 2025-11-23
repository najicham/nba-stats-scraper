
# 2025-05-27

* documented gcloud commands in Nuclino and in gcloud-setup/docs

* shell script to create gcloud configuration
** ~/gcloud-setup/create_gcloud_config.sh

* shell script to create python virtual env

* shell script to create 


so we have a python virtual env, a way to create configurations,
a way to deploy functions and schedules


first step now:
* let's create the configurations and play with them
* use the aliases to manage them

## Gcloud Config
* dealing with a few things, which project, which account, and which ADC

# CLI – replace YOUR_EMAIL and YOUR_PROJECT
gcloud projects add-iam-policy-binding scrape-sports-25 \
    --member="user:nchammas@gmail.com" \
    --role="roles/serviceusage.serviceUsageConsumer"

gcloud auth application-default set-quota-project scrape-sports-25

gcloud config configurations create nba-props
gcloud config set project nba-props-platform
gcloud config set account nchammas@gmail.com

ran a script to create gcloud projects



gcloud config configurations list

gcloud config configurations create nba-props
# inside the nba-props config
gcloud config set project nba-props-platform
gcloud config set account nchammas@gmail.com

gcloud config configurations activate recipe

# General form
gcloud config configurations delete <CONFIG_NAME>

# Example
gcloud config configurations delete shipstats

~/gcloud-setup [scrape-sports-25] gcswitch nba-props
Activated [nba-props].
[core]
account = nchammas@gmail.com
disable_usage_reporting = True
project = nba-props-platform

Your active configuration is: [nba-props]







