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

st.title("Azure – Recommandations & Coûts (Final)")

# ---- Récupération des subscriptions avec cache ----
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

# ---- Fonction principale avec cache ----
@st.cache_data(ttl=1800)
def get_azure_data(selected_subs, sub_options):
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

            # ---- Traitement sécurisé des rows
            for row in cost_query.rows:
                rg_name = row[0] if row[0] else "N/A"
                raw_cost = row[1]
                try:
                    cost_value = float(str(raw_cost).replace(",", ".").strip())
                    cost_data_all.append([sub_name, rg_name, round(cost_value, 2)])
                except (TypeError, ValueError):
                    st.write(f"Ignored row {row} in subscription {sub_name}: not numeric")
                    continue

        except Exception as e:
            st.write(f"Erreur sur subscription {sub_name}: {e}")

        time.sleep(2)  # pause pour éviter 429

    df_recs = pd.DataFrame(advisor_recs, columns=["Subscription", "Catégorie", "Problème", "Solution", "Impact", "Resource Group"])
    df_costs = pd.DataFrame(cost_data_all, columns=["Subscription", "Resource Group", "Coût (€)"])
    
    return df_recs, df_costs

# ---- Bouton Analyse ----
if st.button("Analyser Azure"):
    if not selected_subs:
        st.warning("Veuillez sélectionner au moins une subscription.")
    else:
        df_recs, df_costs = get_azure_data(selected_subs, sub_options)

        st.subheader("Recommandations Azure Advisor")
        st.dataframe(df_recs)

        st.subheader("Analyse des coûts (30 derniers jours)")
        st.dataframe(df_costs)

        # ---- Graphiques ----
        if not df_costs.empty:
            fig1, ax1 = plt.subplots()
            df_costs.groupby("Resource Group")["Coût (€)"].sum().sort_values(ascending=False).head(10).plot(kind="bar", ax=ax1)
            ax1.set_ylabel("Coût (€)")
            ax1.set_title("Top Resource Groups par coût (30j)")
            st.pyplot(fig1)
        else:
            st.info("Aucune donnée de coût disponible pour les graphiques.")

        if not df_recs.empty:
            fig2, ax2 = plt.subplots()
            df_recs.groupby("Resource Group").size().sort_values(ascending=False).head(10).plot(kind="bar", ax=ax2)
            ax2.set_ylabel("Nombre de recommandations")
            ax2.set_title("Top Resource Groups avec recommandations")
            st.pyplot(fig2)
        else:
            st.info("Aucune recommandation disponible pour les graphiques.")

        # ---- Génération PDF ----
        def generate_pdf(df_recs, df_costs):
            buffer = BytesIO()
            c = canvas.Canvas(buffer, pagesize=A4)

            c.setFont("Helvetica-Bold", 16)
            c.drawString(80, 800, "Rapport Azure – Coûts & Recommandations")
            c.setFont("Helvetica", 12)
            c.drawString(50, 770, f"Nombre total de recommandations : {len(df_recs)}")
            c.drawString(50, 755, f"Nombre de Resource Groups impactés (recs) : {df_recs['Resource Group'].nunique()}")
            c.drawString(50, 740, f"Nombre de Resource Groups facturés : {df_costs['Resource Group'].nunique()}")
            c.drawString(50, 725, f"Coût total (30j) : {df_costs['Coût (€)'].sum():.2f} €")

            # ---- Tableau Recs
            if not df_recs.empty:
                rec_columns_order = ["Subscription","Catégorie","Problème","Solution","Impact","Resource Group"]
                table_recs = Table([rec_columns_order] + df_recs[rec_columns_order].values.tolist(), colWidths=[80,70,120,120,60,70])
                table_recs.setStyle(TableStyle([
                    ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#2E86C1")),
                    ("TEXTCOLOR",(0,0),(-1,0),colors.white),
                    ("ALIGN",(0,0),(-1,-1),"CENTER"),
                    ("GRID",(0,0),(-1,-1),0.25,colors.grey),
                    ("FONTSIZE",(0,0),(-1,-1),5)
                ]))
                table_recs.wrapOn(c,50,600)
                table_recs.drawOn(c,50,500)

            # ---- Tableau Coûts
            if not df_costs.empty:
                cost_columns_order = ["Subscription","Resource Group","Coût (€)"]
                df_costs_pdf = df_costs.copy()
                df_costs_pdf["Coût (€)"] = df_costs_pdf["Coût (€)"].apply(lambda x: f"{x:.2f}")
                table_costs = Table([cost_columns_order] + df_costs_pdf[cost_columns_order].values.tolist(), colWidths=[100,150,100])
                table_costs.setStyle(TableStyle([
                    ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#27AE60")),
                    ("TEXTCOLOR",(0,0),(-1,0),colors.white),
                    ("ALIGN",(0,0),(-1,-1),"CENTER"),
                    ("GRID",(0,0),(-1,-1),0.25,colors.grey),
                    ("FONTSIZE",(0,0),(-1,-1),6)
                ]))
                table_costs.wrapOn(c,50,400)
                table_costs.drawOn(c,50,300)

            c.save()
            buffer.seek(0)
            return buffer

        pdf_bytes = generate_pdf(df_recs, df_costs)
        st.download_button(
            label="📥 Télécharger le rapport PDF",
            data=pdf_bytes,
            file_name="azure_report.pdf",
            mime="application/pdf"
        )
