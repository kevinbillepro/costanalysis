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
from datetime import datetime
import calendar
from concurrent.futures import ThreadPoolExecutor, as_completed

st.title("Azure – Recommandations & Coûts (Optimisé par mois)")

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

# ---- Sélection de mois et année ----
current_year = datetime.utcnow().year
years = [current_year-1, current_year]
months = list(range(1, 13))

selected_year = st.selectbox("Sélectionnez l'année", years, index=1)
selected_month = st.selectbox("Sélectionnez le mois", months, index=datetime.utcnow().month-1)

start_date = datetime(selected_year, selected_month, 1)
end_day = calendar.monthrange(selected_year, selected_month)[1]
end_date = datetime(selected_year, selected_month, end_day)

start_date_str = start_date.replace(microsecond=0).isoformat() + "Z"
end_date_str = end_date.replace(microsecond=0).isoformat() + "Z"

st.write(f"Analyse des coûts pour : {calendar.month_name[selected_month]} {selected_year}")

# ---- Fonction pour une subscription (cache individuel) ----
@st.cache_data(ttl=1800)
def get_subscription_data(sub_id, sub_name, start_date_str, end_date_str):
    credential = ClientSecretCredential(
        tenant_id=st.secrets["AZURE_TENANT_ID"],
        client_id=st.secrets["AZURE_CLIENT_ID"],
        client_secret=st.secrets["AZURE_CLIENT_SECRET"]
    )

    advisor_recs = []
    cost_data_all = []

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
                "timePeriod": {"from": start_date_str, "to": end_date_str},
                "dataset": {
                    "granularity": "None",
                    "aggregation": {"totalCost": {"name": "PreTaxCost", "function": "Sum"}},
                    "grouping": [{"type": "Dimension", "name": "ResourceGroupName"}],
                },
            },
        )

        for row in cost_query.rows:
            rg_name = row[1] if row[1] else "N/A"
            raw_cost = row[0]
            try:
                cost_value = float(str(raw_cost).replace(",", ".").strip())
                cost_data_all.append([sub_name, rg_name, round(cost_value, 2)])
            except (TypeError, ValueError):
                continue
    except Exception as e:
        st.warning(f"Erreur subscription {sub_name}: {e}")

    time.sleep(1)
    return advisor_recs, cost_data_all

# ---- Génération Excel ----
def generate_excel(df_costs):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df_costs.to_excel(writer, sheet_name="Coûts détaillés", index=False)
        df_total = df_costs.groupby("Subscription")["Coût (€)"].sum().reset_index()
        df_total["Coût (€)"] = df_total["Coût (€)"].round(2)
        df_total.to_excel(writer, sheet_name="Total par subscription", index=False)
        writer.save()
        output.seek(0)
    return output

# ---- Analyse multi-subscriptions avec ThreadPool ----
if st.button("Analyser Azure"):
    if not selected_subs:
        st.warning("Veuillez sélectionner au moins une subscription.")
    else:
        advisor_recs = []
        cost_data_all = []

        progress_bar = st.progress(0)
        total = len(selected_subs)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(get_subscription_data, sub_id,
                                next(name for name, sid in sub_options.items() if sid == sub_id),
                                start_date_str, end_date_str): sub_id
                for sub_id in selected_subs
            }
            for i, future in enumerate(as_completed(futures)):
                recs, costs = future.result()
                advisor_recs.extend(recs)
                cost_data_all.extend(costs)
                progress_bar.progress((i+1)/total)

        df_recs = pd.DataFrame(advisor_recs, columns=["Subscription", "Catégorie", "Problème", "Solution", "Impact", "Resource Group"])
        df_costs = pd.DataFrame(cost_data_all, columns=["Subscription", "Resource Group", "Coût (€)"])

        st.subheader("Recommandations Azure Advisor")
        st.dataframe(df_recs)

        st.subheader(f"Analyse des coûts ({calendar.month_name[selected_month]} {selected_year})")
        st.dataframe(df_costs)

        # Total par subscription
        if not df_costs.empty:
            df_costs_sub = df_costs.groupby("Subscription")["Coût (€)"].sum().reset_index()
            df_costs_sub["Coût (€)"] = df_costs_sub["Coût (€)"].round(2)
            st.subheader("Total des coûts par subscription")
            st.dataframe(df_costs_sub)

            # Bouton Excel
            excel_file = generate_excel(df_costs)
            st.download_button(
                label="📥 Télécharger le rapport Excel",
                data=excel_file,
                file_name=f"azure_costs_{selected_year}_{selected_month}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        # Graphiques
        if not df_costs.empty:
            fig1, ax1 = plt.subplots()
            df_costs.groupby("Resource Group")["Coût (€)"].sum().sort_values(ascending=False).head(10).plot(kind="bar", ax=ax1)
            ax1.set_ylabel("Coût (€)")
            ax1.set_title(f"Top Resource Groups par coût ({calendar.month_name[selected_month]} {selected_year})")
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

        # PDF
        def generate_pdf(df_recs, df_costs):
            buffer = BytesIO()
            c = canvas.Canvas(buffer, pagesize=A4)
            c.setFont("Helvetica-Bold", 16)
            c.drawString(80, 800, f"Rapport Azure – {calendar.month_name[selected_month]} {selected_year}")
            c.setFont("Helvetica", 12)
            c.drawString(50, 770, f"Nombre total de recommandations : {len(df_recs)}")
            c.drawString(50, 755, f"Nombre de Resource Groups impactés (recs) : {df_recs['Resource Group'].nunique()}")
            c.drawString(50, 740, f"Nombre de Resource Groups facturés : {df_costs['Resource Group'].nunique()}")
            c.drawString(50, 725, f"Coût total : {df_costs['Coût (€)'].sum():.2f} €")

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
            file_name=f"azure_report_{selected_year}_{selected_month}.pdf",
            mime="application/pdf"
        )
