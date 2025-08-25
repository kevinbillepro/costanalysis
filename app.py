import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors

# Azure SDK
from azure.identity import ClientSecretCredential
from azure.mgmt.advisor import AdvisorManagementClient
from azure.mgmt.resource import SubscriptionClient
from azure.mgmt.costmanagement import CostManagementClient

# --------------------------
# 1. Connexion Azure
# --------------------------
tenant_id = st.secrets["AZURE_TENANT_ID"]
client_id = st.secrets["AZURE_CLIENT_ID"]
client_secret = st.secrets["AZURE_CLIENT_SECRET"]

credential = ClientSecretCredential(
    tenant_id=tenant_id,
    client_id=client_id,
    client_secret=client_secret
)

# --------------------------
# 2. Récupérer toutes les subscriptions
# --------------------------
sub_client = SubscriptionClient(credential)
subscriptions = list(sub_client.subscriptions.list())
subscription_dict = {sub.display_name: sub.subscription_id for sub in subscriptions}

st.title("☁️ Azure Advisor + Analyse Coûts (Production)")
st.write("Sélectionnez une subscription pour générer un rapport avec recommandations et coûts réels.")

selected_name = st.selectbox("Choisir une subscription :", list(subscription_dict.keys()))
subscription_id = subscription_dict[selected_name]

# --------------------------
# 3. Récupération recommandations Advisor
# --------------------------
advisor_client = AdvisorManagementClient(credential, subscription_id)
recs = []
for rec in advisor_client.recommendations.list():
    resource_id = getattr(rec.impacted_value, 'resource_id', 'N/A')
    recs.append([
        rec.category,
        rec.short_description.problem,
        rec.short_description.solution,
        rec.impact,
        resource_id
    ])

df_recs = pd.DataFrame(recs, columns=["Catégorie", "Problème", "Solution", "Impact", "Ressource"])

# --------------------------
# 4. Récupération coûts réels
# --------------------------
cost_client = CostManagementClient(credential)
scope = f"/subscriptions/{subscription_id}"

# Exemple : coûts des 30 derniers jours
query = {
    "type": "ActualCost",
    "timeframe": "MonthToDate",
    "dataset": {
        "granularity": "None",
        "grouping": [{"type": "Dimension", "name": "ResourceId"}],
        "aggregation": {"totalCost": {"name": "PreTaxCost", "function": "Sum"}}
    }
}

results = cost_client.query.usage(scope, query)

# Convertir en DataFrame
costs = []
for row in results.rows:
    resource_id = row[0]
    total_cost = float(row[1])
    costs.append([resource_id, total_cost])

df_costs = pd.DataFrame(costs, columns=["Ressource", "Coût actuel (€)"])

# --------------------------
# 5. Fusion Advisor + Coût
# --------------------------
df_final = pd.merge(df_recs, df_costs, on="Ressource", how="left")
df_final["Économie potentielle (€)"] = df_final["Coût actuel (€)"] * 0.3  # estimation 30%

# --------------------------
# 6. Affichage tableau
# --------------------------
st.subheader(f"📊 Recommandations & Coûts - {selected_name}")
st.dataframe(df_final)

# --------------------------
# 7. Graphique
# --------------------------
fig, ax = plt.subplots()
df_final.groupby("Catégorie")["Économie potentielle (€)"].sum().plot(
    kind="bar", ax=ax, color="green"
)
ax.set_title("Économie potentielle par catégorie")
ax.set_ylabel("€")
st.pyplot(fig)

# --------------------------
# 8. Génération PDF
# --------------------------
def generate_pdf(dataframe, subscription_name):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(80, 800, f"Rapport Azure Advisor + Coûts Réels")
    c.setFont("Helvetica", 12)
    c.drawString(80, 780, f"Subscription : {subscription_name}")

    # Tableau
    table_data = [["Catégorie","Problème","Solution","Impact","Ressource","Coût actuel (€)","Économie potentielle (€)"]] \
                 + dataframe.values.tolist()
    table = Table(table_data, colWidths=[80,120,120,60,150,80,100])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#2E86C1")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("FONTSIZE", (0,0), (-1,-1), 7),
    ]))
    table.wrapOn(c, 50, 600)
    table.drawOn(c, 50, 600)

    c.setFont("Helvetica", 10)
    total_saving = dataframe["Économie potentielle (€)"].sum()
    c.drawString(50, 560, f"Nombre de recommandations : {len(dataframe)} | Économie totale potentielle : €{total_saving:.2f}")

    c.save()
    buffer.seek(0)
    return buffer

pdf_bytes = generate_pdf(df_final, selected_name)

st.download_button(
    label="📥 Télécharger le rapport PDF",
    data=pdf_bytes,
    file_name=f"azure_cost_report_{selected_name}.pdf",
    mime="application/pdf"
)
