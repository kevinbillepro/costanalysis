import streamlit as st
import pandas as pd
import subprocess
import json
import matplotlib.pyplot as plt
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors

st.title("Azure Advisor + Bash CLI + PDF")

# Input subscription
subscription_id = st.text_input("Entrez votre Subscription ID")

if st.button("Récupérer les coûts"):
    if not subscription_id:
        st.warning("Veuillez saisir une subscription ID")
    else:
        try:
            # Exécuter le script Bash
            result = subprocess.run(
                ["bash", "script_azure.sh", subscription_id],
                capture_output=True,
                text=True
            )
            costs_json = json.loads(result.stdout)
            df_costs = pd.DataFrame(costs_json)
            df_costs.rename(columns={"Resource":"Ressource","Cost":"Coût actuel (€)"}, inplace=True)

            # Exemple : Ajouter colonne économie potentielle 30%
            df_costs["Économie potentielle (€)"] = df_costs["Coût actuel (€)"] * 0.3

            st.subheader("Tableau des coûts et économies potentielles")
            st.dataframe(df_costs)

            # Graphique
            fig, ax = plt.subplots()
            df_costs.sort_values("Économie potentielle (€)", ascending=False).head(10)\
                .plot(kind="bar", x="Ressource", y="Économie potentielle (€)", ax=ax, color="green")
            ax.set_ylabel("€")
            ax.set_title("Top 10 économies potentielles")
            st.pyplot(fig)

            # Génération PDF
            def generate_pdf(df, subscription_id):
                buffer = BytesIO()
                c = canvas.Canvas(buffer, pagesize=A4)
                c.setFont("Helvetica-Bold", 16)
                c.drawString(80, 800, f"Rapport Azure Coûts via Bash CLI")
                c.setFont("Helvetica", 12)
                c.drawString(80, 780, f"Subscription : {subscription_id}")

                table_data = [["Ressource","Coût actuel (€)","Économie potentielle (€)"]] + df.values.tolist()
                table = Table(table_data, colWidths=[250,100,100])
                table.setStyle(TableStyle([
                    ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#2E86C1")),
                    ("TEXTCOLOR",(0,0),(-1,0),colors.white),
                    ("ALIGN",(0,0),(-1,-1),"CENTER"),
                    ("GRID",(0,0),(-1,-1),0.5,colors.grey),
                    ("FONTSIZE",(0,0),(-1,-1),8)
                ]))
                table.wrapOn(c,50,600)
                table.drawOn(c,50,600)

                total_saving = df["Économie potentielle (€)"].sum()
                c.drawString(50,560,f"Nombre de ressources : {len(df)} | Économie totale potentielle : €{total_saving:.2f}")
                c.save()
                buffer.seek(0)
                return buffer

            pdf_bytes = generate_pdf(df_costs, subscription_id)
            st.download_button(
                label="📥 Télécharger PDF",
                data=pdf_bytes,
                file_name=f"azure_cost_report_{subscription_id}.pdf",
                mime="application/pdf"
            )

        except Exception as e:
            st.error(f"Erreur : {e}")
