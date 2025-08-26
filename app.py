import streamlit as st
import pandas as pd
from azure.identity import ClientSecretCredential
from azure.mgmt.advisor import AdvisorManagementClient
from azure.mgmt.costmanagement import CostManagementClient
import matplotlib.pyplot as plt
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from datetime import datetime, timedelta
today = datetime.utcnow()
from azure.mgmt.resource import SubscriptionClient

st.title("Azure – Recommandations & Coûts (Multi-subscriptions)")

# --------------------------
# 1. Connexion Azure via Service Principal
# --------------------------
tenant_id = st.secrets["AZURE_TENANT_ID"]
client_id = st.secrets["AZURE_CLIENT_ID"]
client_secret = st.secrets["AZURE_CLIENT_SECRET"]

credential = ClientSecretCredential(
    tenant_id=tenant_id,
    client_id=client_id,
    client_secret=client_secret
)
if st.button("Analyser Azure"):
    try:
        # 🔐 Connexion
        credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret
        )

        # 📌 Récupération automatique des subscriptions
        sub_client = SubscriptionClient(credential)
        subscriptions = [sub.subscription_id for sub in sub_client.subscriptions.list()]

        advisor_recs = []
        cost_data_all = []

        for sub_id in subscriptions:
            # ---- Azure Advisor
            advisor_client = AdvisorManagementClient(credential, sub_id)
            for rec in advisor_client.recommendations.list():
                resource_group = getattr(getattr(rec, "resource_metadata", None), "resource_group", "N/A")
                advisor_recs.append([
                    sub_id,
                    rec.category,
                    rec.short_description.problem,
                    rec.short_description.solution,
                    rec.impact,
                    resource_group
                ])

            # ---- Cost Management (30 derniers jours)
            cost_client = CostManagementClient(credential)
            today = datetime.utcnow()
            start_date = (today - timedelta(days=30)).replace(microsecond=0).isoformat() + "Z"
            end_date = today.replace(microsecond=0).isoformat() + "Z"

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

            for row in cost_query.rows:
                cost_data_all.append([sub_id, row[0], row[1]])

        # ---- DataFrames
        df_recs = pd.DataFrame(advisor_recs, columns=["Subscription", "Catégorie", "Problème", "Solution", "Impact", "Resource Group"])
        df_costs = pd.DataFrame(cost_data_all, columns=["Subscription", "Resource Group", "Coût (€)"])

        # ---- Affichage Streamlit
        st.subheader("Recommandations Azure Advisor")
        st.dataframe(df_recs)

        st.subheader("Analyse des coûts (30 derniers jours)")
        st.dataframe(df_costs)

        # Graphiques
        fig1, ax1 = plt.subplots()
        df_costs.groupby("Resource Group")["Coût (€)"].sum().sort_values(ascending=False).head(10).plot(kind="bar", ax=ax1)
        ax1.set_ylabel("Coût (€)")
        ax1.set_title("Top Resource Groups par coût (30j)")
        st.pyplot(fig1)

        fig2, ax2 = plt.subplots()
        df_recs.groupby("Resource Group").size().sort_values(ascending=False).head(10).plot(kind="bar", ax=ax2)
        ax2.set_ylabel("Nombre de recommandations")
        ax2.set_title("Top Resource Groups avec recommandations")
        st.pyplot(fig2)

        # ---- Génération PDF
        def generate_pdf(df_recs, df_costs):
            buffer = BytesIO()
            c = canvas.Canvas(buffer, pagesize=A4)

            # Titre
            c.setFont("Helvetica-Bold", 16)
            c.drawString(80, 800, "Rapport Azure – Coûts & Recommandations")
            c.setFont("Helvetica", 12)

            # Résumé global
            c.drawString(50, 770, f"Nombre total de recommandations : {len(df_recs)}")
            c.drawString(50, 755, f"Nombre de Resource Groups impactés (recs) : {df_recs['Resource Group'].nunique()}")
            c.drawString(50, 740, f"Nombre de Resource Groups facturés : {df_costs['Resource Group'].nunique()}")
            c.drawString(50, 725, f"Coût total (30j) : {df_costs['Coût (€)'].sum():.2f} €")

            # Tableau Recommandations
            c.setFont("Helvetica-Bold", 14)
            c.drawString(50, 700, "Recommandations Azure Advisor")
            table_recs = Table([df_recs.columns.tolist()] + df_recs.values.tolist(), colWidths=[70,70,120,120,60,70])
            table_recs.setStyle(TableStyle([
                ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#2E86C1")),
                ("TEXTCOLOR",(0,0),(-1,0),colors.white),
                ("ALIGN",(0,0),(-1,-1),"CENTER"),
                ("GRID",(0,0),(-1,-1),0.25,colors.grey),
                ("FONTSIZE",(0,0),(-1,-1),5)
            ]))
            table_recs.wrapOn(c,50,600)
            table_recs.drawOn(c,50,500)

            # Tableau Coûts
            c.setFont("Helvetica-Bold", 14)
            c.drawString(50, 480, "Analyse des coûts (30 derniers jours)")
            table_costs = Table([df_costs.columns.tolist()] + df_costs.values.tolist(), colWidths=[100,150,100])
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

    except Exception as e:
        st.error(f"Erreur : {e}")

 time.sleep(2)  # 👈 pause 2 sec entre chaque appel
