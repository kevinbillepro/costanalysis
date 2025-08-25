#!/bin/bash
# Ce script récupère les coûts réels sur la subscription active
# Prérequis : az login déjà effectué

SUBSCRIPTION_ID=$1
az account set --subscription $SUBSCRIPTION_ID

# Récupérer les coûts des 30 derniers jours par ressource
az costmanagement query \
    --type Usage \
    --timeframe MonthToDate \
    --dataset-aggregation TotalCost=Sum \
    --dataset-grouping Type=Dimension Name=ResourceId \
    --query "[].{Resource:properties/resourceId, Cost:properties/totalCost}" \
    -o json
