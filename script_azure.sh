#!/bin/bash
# Usage: ./get_costs.sh <subscription_id>
SUBSCRIPTION_ID=$1
az account set --subscription $SUBSCRIPTION_ID

# Récupération des coûts des 30 derniers jours par ressource
az costmanagement query \
  --type Usage \
  --timeframe MonthToDate \
  --dataset-aggregation TotalCost=Sum \
  --dataset-grouping Type=Dimension Name=ResourceId \
  --query "[].{Resource:properties/resourceId, Cost:properties/totalCost}" \
  -o json
