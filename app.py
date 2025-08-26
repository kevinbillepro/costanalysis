import time
import streamlit as st
import pandas as pd
from azure.identity import ClientSecretCredential
from azure.mgmt.advisor import AdvisorManagementClient
from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.resource import SubscriptionClient
import matplotlib.pyplot as plt
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from datetime import datetime, timedelta

st.title("Azure – Recommandations & Coûts (Debug)")

@st.cache_data(ttl=3600)
def get_subscriptions():
    credential = ClientSecretCredential(
        tenant_id=st.secrets["AZURE_TENANT_ID"],
        client_id=st.secrets["AZURE_CLIENT_ID"],
        client_secret=st.secrets["AZURE_CLIENT_SECRET"]
    )
    sub_client = SubscriptionClient(credential)
    return [(sub.subscription_id, sub.display_name) for sub in sub_client.subscriptions.list()]

subs = get_subscriptions()
sub_options = {name: sub_id for sub_id, name in subs}

selected_names = st.multiselect(
    "Sélectionnez les subscriptions à analyser",
    options=list(sub_options.keys()),
    default=list(sub_options.keys())
)

selected_subs = [sub_options[name] for name in selected_names]

@st.cache_data(ttl=1800)
def get_azure_data_debug(selected_subs, sub_options):
    credential = ClientSecretCredential(
        tenant_id=st.secrets["AZURE_TENANT_ID"],
        client_id=st.secrets["AZURE_CLIENT_ID"],
        client_secret=st.secrets["AZURE_CLIENT_SECRET"]
    )

    advisor_recs = []
    cost_data_all = []

    today = datetime.utcnow()
    start_date = (today - timedelta(days=30)).replace(microsecond=0).isoformat() + "Z"
    end_date = today.replace(microsecond=0).isoformat() + "Z"

    for sub_id in selected_subs:
        sub_name = next((name for name, sid in sub_options.items() if sid == sub_id), sub_id)

        # ---- Advisor
        advisor_client = AdvisorManagementClient(credential, sub_id)
        for rec in advisor_client.recommendations.list():
            resource_group = getattr(getattr(rec, "resource_metadata", None), "resource_group", "N/A")
            advisor_recs.append([
                sub_name,
                rec.category,
                rec.short_description.problem,
                rec.short_description.solution,
                rec.impact,
                resource_group
            ])

        # ---- Cost Management
        cost_client = CostManagementClient(credential)
        try:
            cost_query = cost_client.query.usage(
                scope=f"/subscriptions/{sub_id}",
                parameters={
                    "type": "ActualCost",
                    "timeframe": "Custom",
                    "timePeriod": {"from": start_date, "to": end_date},
                    "dataset": {
                        "granularity": "None",
                        "aggregation": {"totalCost": {"name": "PreTaxCost", "function": "Sum"}},
                        "grouping": [{"type": "Dimension", "name": "ResourceGroupName"}],
                    },
                },
            )

            st.write(f"DEBUG subscription {sub_name} rows raw:")
            st.write(cost_query.rows)  # Affiche le contenu brut

            for row in cost_query.rows:
                try:
                    cost_value = float(str(row[1]).replace(",", ".").strip())
                    cost_data_all.append([sub_name, row[0], round(cost_value, 2)])
                except (TypeError, ValueError) as e:
                    st.write(f"Ignored row {row} in subscription {sub_name}: {e}")

        except Exception as e:
            st.write(f"Erreur sur subscription {sub_name}: {e}")

        time.sleep(2)

    df_recs = pd.DataFrame(advisor_recs, columns=["Subscription", "Catégorie", "Problème", "Solution", "Impact", "Resource Group"])
    df_costs = pd.DataFrame(cost_data_all, columns=["Subscription", "Resource Group", "Coût (€)"])
    
    return df_recs, df_costs

if st.button("Analyser Azure (Debug)"):
    if not selected_subs:
        st.warning("Veuillez sélectionner au moins une subscription.")
    else:
        df_recs, df_costs = get_azure_data_debug(selected_subs, sub_options)
        st.subheader("Recommandations Azure Advisor")
        st.dataframe(df_recs)
        st.subheader("Analyse des coûts (30 derniers jours)")
        st.dataframe(df_costs)
