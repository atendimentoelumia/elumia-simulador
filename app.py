import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import requests
import re
import hashlib
from io import BytesIO

# Importações para o ecossistema Google Drive API
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# Importações para o motor de PDF (ReportLab)
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# Configuração da página - E-Lumia Executive BI
st.set_page_config(page_title="E-Lumia | Hub Solution Intelligence", layout="wide", initial_sidebar_state="expanded")

# CSS Ajustado para Dark Mode Premium
st.markdown("""
    <style>
    .card-vendas { background-color: #1E293B; padding: 22px; border-radius: 12px; border-left: 6px solid #3B82F6; margin-bottom: 20px; color: #F8FAFC; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }
    .card-comercializadora { background-color: #0F172A; padding: 15px; border-radius: 8px; border: 1px solid #334155; text-align: center; color: #E2E8F0; }
    .destaque-ganho { color: #4ADE80; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

MAPA_IMPOSTOS = {
    "ENEL SP": {"UF": "SP", "ICMS": 0.18, "PIS_COFINS": 0.0925},
    "CPFL PAULISTA": {"UF": "SP", "ICMS": 0.18, "PIS_COFINS": 0.0925},
    "CEMIG": {"UF": "MG", "ICMS": 0.18, "PIS_COFINS": 0.0925},
    "COPEL": {"UF": "PR", "ICMS": 0.19, "PIS_COFINS": 0.0925},
    "LIGHT": {"UF": "RJ", "ICMS": 0.18, "PIS_COFINS": 0.0925},
    "AMAZONAS ENERGIA": {"UF": "AM", "ICMS": 0.18, "PIS_COFINS": 0.0925},
    "EQUATORIAL MA": {"UF": "MA", "ICMS": 0.20, "PIS_COFINS": 0.0925},
}

NOME_ARQUIVO_CSV = "tarifas.csv"

@st.cache_data
def load_local_data():
    try:
        df = pd.read_csv(NOME_ARQUIVO_CSV, sep=None, engine='python', encoding='utf-8-sig', on_bad_lines='skip')
        df.columns = df.columns.str.strip()
        return df
    except Exception as e:
        st.sidebar.error(f"Erro ao ler o arquivo local {NOME_ARQUIVO_CSV}: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=86400)
def fetch_aneel_companies():
    df = load_local_data()
    if not df.empty:
        col_sigla = next((col for col in df.columns if 'sigla' in col.lower()), None)
        if col_sigla:
            return sorted(df[col_sigla].dropna().unique().tolist())
    return list(MAPA_IMPOSTOS.keys())

@st.cache_data(ttl=3600)
def fetch_fatura_data(concessionaria, subgrupo, modalidade):
    df = load_local_data()
    tusd_demanda, tusd_energia_fp, tusd_energia_p, te_fp, te_p = 45.00, 80.0, 250.0, 320.0, 550.0
    
    if not df.empty:
        try:
            col_sigla = next((c for c in df.columns if 'sigla' in c.lower()), None)
            col_sub = next((c for c in df.columns if 'subgrupo' in c.lower()), None)
            col_mod = next((c for c in df.columns if 'modalidade' in c.lower()), None)
            col_posto = next((c for c in df.columns if 'posto' in c.lower()), None)
            col_te = next((c for c in df.columns if 'te' in c.lower() and ('vlr' in c.lower() or 'valor' in c.lower())), None)
            col_tusd = next((c for c in df.columns if 'tusd' in c.lower() and ('vlr' in c.lower() or 'valor' in c.lower())), None)

            if all([col_sigla, col_sub, col_mod]):
                mask = (df[col_sigla] == concessionaria) & (df[col_sub] == subgrupo) & (df[col_mod] == modalidade)
                df_filtered = df[mask].copy()

                if not df_filtered.empty:
                    if col_te:
                        df_filtered[col_te] = pd.to_numeric(df_filtered[col_te].astype(str).str.replace(',', '.'), errors='coerce').fillna(0) * (1000 if df_filtered[col_te].max() < 10 else 1)
                    if col_tusd:
                        df_filtered[col_tusd] = pd.to_numeric(df_filtered[col_tusd].astype(str).str.replace(',', '.'), errors='coerce').fillna(0) * (1000 if df_filtered[col_tusd].max() < 10 else 1)

                    tusd_demanda = 42.50 if modalidade == "Azul" else 20.80
                    
                    if col_posto:
                        df_filtered['posto_clean'] = df_filtered[col_posto].astype(str).str.lower().str.strip()
                        df_fp = df_filtered[df_filtered['posto_clean'].str.contains('fora ponta', na=False)]
                        df_p = df_filtered[df_filtered['posto_clean'].str.contains('ponta', na=False) & ~df_filtered['posto_clean'].str.contains('fora ponta', na=False)]
                        
                        if not df_fp.empty:
                            if col_te: te_fp = df_fp[col_te].mean()
                            if col_tusd: tusd_energia_fp = df_fp[col_tusd].mean()
                        if not df_p.empty:
                            if col_te: te_p = df_p[col_te].mean()
                            if col_tusd: tusd_energia_p = df_p[col_tusd].mean()
        except Exception as e:
            st.sidebar.warning(f"Aviso: Erro ao processar dados internos do CSV ({e}).")

    return {"tusd_demanda": tusd_demanda, "tusd_energia_p": tusd_energia_p, "tusd_energia_fp": tusd_energia_fp, "te_p": te_p, "te_fp": te_fp}

# --- BARRA LATERAL: ENTRADA DE DADOS ---
st.sidebar.header("🎯 Qualificação do Cliente")

if "nome_cliente_auto" not in st.session_state:
    st.session_state.nome_cliente_auto = ""

cnpj_input = st.sidebar.text_input("CNPJ (Aperte Enter)", placeholder="00.000.000/0000-00")
cnpj_limpo = re.sub(r'[^0-9]', '', cnpj_input)

if len(cnpj_limpo) == 14:
    with st.sidebar.spinner("Buscando dados da Receita..."):
        try:
            response = requests.get(f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}", timeout=8)
            if response.status_code == 200:
                st.session_state.nome_cliente_auto = response.json().get('razao_social', '')
                st.sidebar.success("CNPJ Localizado!")
        except Exception:
            pass

nome_cliente = st.sidebar.text_input("Nome / Razão Social", value=st.session_state.nome_cliente_auto)

list_concessionarias = fetch_aneel_companies()
concessionaria = st.sidebar.selectbox("Distribuidora Atual", list_concessionarias)

dados_fiscais = MAPA_IMPOSTOS.get(concessionaria, {"UF": "SP", "ICMS": 0.18, "PIS_COFINS": 0.0925})
impostos_totais = dados_fiscais["ICMS"] + dados_fiscais["PIS_COFINS"]

subgrupo = st.sidebar.selectbox("Subgrupo Tarifário", ["A4", "A3"])
modalidade = st.sidebar.selectbox("Modalidade na Distribuidora", ["Verde", "Azul"])
tempo_contrato = st.sidebar.slider("Horizonte (Meses)", 12, 60, 36, step=12)
tipo_energia = st.sidebar.selectbox("Produto Sugerido", ["Convencional", "Incentivada 50%", "Incentivada 100%"])

fator_desconto_demanda = 1.0 if tipo_energia == "Convencional" else (0.5 if tipo_energia == "Incentivada 50%" else 0.0)

st.sidebar.subheader("📊 Métricas de Consumo")
demanda_contratada = st.sidebar.number_input("Demanda Contratada (kW)", value=500.0)
consumo_kwh_fp = st.sidebar.number_input("Consumo Fora Ponta (kWh/mês)", value=120000.0, step=5000.0)
consumo_kwh_p = st.sidebar.number_input("Consumo Ponta (kWh/mês)", value=15000.0, step=1000.0)
fee_elumia_mwh = st.sidebar.number_input("Gestão Executiva E-Lumia (R$/MWh)", value=6.00, format="%.2f")

consumo_fp = consumo_kwh_fp / 1000
consumo_p = consumo_kwh_p / 1000
consumo_total_mes_kwh = consumo_kwh_fp + consumo_kwh_p
consumo_total_ano_mwh = (consumo_total_mes_kwh / 1000) * 12

st.sidebar.subheader("🏢 Ofertas de Fornecedores (R$/MWh)")
comercializadoras = ["Casa dos Ventos", "Ecom Energia", "Matrix", "Voltera"]
dados_precos = {}
for com in comercializadoras:
    with st.sidebar.expander(f"Preços - {com}"):
        precos_anos = []
        for ano in range(1, 6):
            p = st.number_input(f"{com} - Ano {ano}", value=180.0 + (ano * 4), key=f"{com}_ano_{ano}")
            precos_anos.append(p)
        dados_precos[com] = precos_anos

componentes = fetch_fatura_data(concessionaria, subgrupo, modalidade)

# --- MATRIZ FINANCEIRA DE PROSPECÇÃO ---
def decompor_item(valor_base):
    valor_com_imposto = valor_base / (1 - impostos_totais)
    imposto_calculado = valor_com_imposto * impostos_totais
    return valor_base, imposto_calculado, valor_com_imposto

_, _, total_demanda_cat = decompor_item(demanda_contratada * componentes["tusd_demanda"])
_, _, total_tusd_p_cat = decompor_item(consumo_p * componentes["tusd_energia_p"])
_, _, total_tusd_fp_cat = decompor_item(consumo_fp * componentes["tusd_energia_fp"])
_, _, total_te_p_cat = decompor_item(consumo_p * componentes["te_p"])
_, _, total_te_fp_cat = decompor_item(consumo_fp * componentes["te_fp"])

fatura_mensal_cativa = total_demanda_cat + total_tusd_p_cat + total_tusd_fp_cat + total_te_p_cat + total_te_fp_cat
_, _, total_demanda_acl = decompor_item(demanda_contratada * componentes["tusd_demanda"] * fator_desconto_demanda)
fatura_residual_concessionaria_acl = total_demanda_acl + total_tusd_p_cat + total_tusd_fp_cat
_, _, total_gestao_elumia_mes = decompor_item((consumo_total_mes_kwh / 1000) * fee_elumia_mwh)

resultados_comercializadoras_mes = {}
for com in comercializadoras:
    preco_ano1 = dados_precos[com][0]
    _, _, total_energia_mes = decompor_item((consumo_total_mes_kwh / 1000) * preco_ano1)
    total_acl = fatura_residual_concessionaria_acl + total_energia_mes + total_gestao_elumia_mes
    resultados_comercializadoras_mes[com] = {
        "fatura_energia": total_energia_mes,
        "custo_total_acl": total_acl,
        "economia_reais": fatura_mensal_cativa - total_acl,
        "percentual": ((fatura_mensal_cativa - total_acl) / fatura_mensal_cativa) * 100
    }

melhor_com_mes = min(resultados_comercializadoras_mes, key=lambda k: resultados_comercializadoras_mes[k]["custo_total_acl"])
dados_melhor = resultados_comercializadoras_mes[melhor_com_mes]

# --- RENDERIZAÇÃO NA TELA ---
st.title("⚡ E-Lumia | Hub Solution Intelligence")
saudacao = f"para <b>{nome_cliente}</b>" if nome_cliente else ""
st.markdown(f"""
<div class="card-vendas">
    <span style="font-size:20px; font-weight:bold; color:#3B82F6;">📈 Diagnóstico Comercial Executivo</span><br/>
    Parceiro mais competitivo selecionado {saudacao}: <b>{melhor_com_mes}</b> com economia de <b>{dados_melhor['percentual']:.1f}%</b>.
</div>
""", unsafe_allow_html=True)

# SEÇÃO: MATRIZ DE PREÇOS COMPLETA INPUTADA (NOVA SOLICITAÇÃO)
st.subheader("🏢 Matriz Global de Ofertas de Fornecedores Mapeados")
st.markdown("Acompanhamento consolidado das curvas de preços de fornecimento inseridas para cada ano de planejamento:")

linhas_matriz_global = []
for com in comercializadoras:
    linhas_matriz_global.append({
        "Comercializadora Mapeada": com,
        "Ano 1 (R$/MWh)": dados_precos[com][0],
        "Ano 2 (R$/MWh)": dados_precos[com][1],
        "Ano 3 (R$/MWh)": dados_precos[com][2],
        "Ano 4 (R$/MWh)": dados_precos[com][3],
        "Ano 5 (R$/MWh)": dados_precos[com][4],
    })
df_matriz_global_tela = pd.DataFrame(linhas_matriz_global)
st.dataframe(df_matriz_global_tela.style.format({
    "Ano 1 (R$/MWh)": "R$ {:,.2f}", "Ano 2 (R$/MWh)": "R$ {:,.2f}", 
    "Ano 3 (R$/MWh)": "R$ {:,.2f}", "Ano 4 (R$/MWh)": "R$ {:,.2f}", "Ano 5 (R$/MWh)": "R$ {:,.2f}"
}), use_container_width=True, hide_index=True)

# COMPARATIVO MENSAL E LONG-TERM
col1, col2 = st.columns(2)
with col1:
    st.markdown("#### **Cenário Cativo**")
    st.dataframe(pd.DataFrame({
        "Componentes de Custo": ["Demanda", "TUSD Ponta", "TUSD F. Ponta", "TE Ponta", "TE F. Ponta"],
        "Valor": [total_demanda_cat, total_tusd_p_cat, total_tusd_fp_cat, total_te_p_cat, total_te_fp_cat]
    }).style.format({"Valor": "R$ {:,.2f}"}), hide_index=True, use_container_width=True)
with col2:
    st.markdown(f"#### **Cenário Livre ({melhor_com_mes})**")
    st.dataframe(pd.DataFrame({
        "Componentes de Custo": ["Demanda TUSD", "TUSD Ponta", "TUSD F. Ponta", "Contrato Energia", "Gestão E-Lumia"],
        "Valor": [total_demanda_acl, total_tusd_p_cat, total_tusd_fp_cat, dados_melhor['fatura_energia'], total_gestao_elumia_mes]
    }).style.format({"Valor": "R$ {:,.2f}"}), hide_index=True, use_container_width=True)

# ENGINE PROJEÇÃO DE ANOS REAIS
linhas_proj = []
anos_reais = int(tempo_contrato / 12)
custo_cativo_acumulado_total = 0
custo_livre_acumulado_total = 0

for ano_idx in range(anos_reais):
    fator_distribuidora = (1 + 0.08) ** ano_idx
    fator_energia_livre = (1 + 0.06) ** ano_idx
    
    custo_cativo_ano = (fatura_mensal_cativa * 12) * fator_distribuidora
    preco_com_inflacao = dados_precos[melhor_com_mes][ano_idx] * fator_energia_livre
    _, _, fatura_energia_ano = decompor_item(consumo_total_ano_mwh * preco_com_inflacao)
    
    fatura_resid_ano = (fatura_residual_concessionaria_acl * 12) * fator_distribuidora
    fee_ano = (total_gestao_elumia_mes * 12) * fator_energia_livre
    custo_acl_ano = fatura_resid_ano + fatura_energia_ano + fee_ano
    
    custo_cativo_acumulado_total += custo_cativo_ano
    custo_livre_acumulado_total += custo_acl_ano
    
    linhas_proj.append({
        "Período": f"Ano {ano_idx + 1}",
        "Custo Projetado no Cativo": custo_cativo_ano,
        f"Custo Otimizado ACL ({melhor_com_mes})": custo_acl_ano,
        "Economia Financeira no Ano": custo_cativo_ano - custo_acl_ano
    })

st.subheader("📈 Estudo de Longo Prazo")
df_estudo_integral = pd.DataFrame(linhas_proj)
st.dataframe(df_estudo_integral.style.format({
    "Custo Projetado no Cativo": "R$ {:,.2f}",
    f"Custo Otimizado ACL ({melhor_com_mes})": "R$ {:,.2f}",
    "Economia Financeira no Ano": "R$ {:,.2f}"
}), use_container_width=True, hide_index=True)

# --- ENGINE DE EXPORTAÇÃO E MONTAGEM DO PDF ESPELHADO ---
def build_pdf():
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=15, textColor=colors.HexColor("#1A365D"), spaceAfter=6, alignment=1)
    subtitle_style = ParagraphStyle('SubTitle', parent=styles['Normal'], fontSize=11, textColor=colors.HexColor("#64748B"), alignment=1, spaceAfter=15)
    h2_style = ParagraphStyle('H2Style', parent=styles['Heading2'], fontSize=12, textColor=colors.HexColor("#1E3A8A"), spaceBefore=12, spaceAfter=6, fontName='Helvetica-Bold')
    normal_style = ParagraphStyle('Norm', parent=styles['Normal'], fontSize=9, spaceAfter=6)
    bold_style = ParagraphStyle('BoldNorm', parent=styles['Normal'], fontSize=9, fontName='Helvetica-Bold', spaceAfter=6)

    story = []
    story.append(Paragraph("PROPOSTA EXECUTIVA DE MIGRAÇÃO - MERCADO LIVRE DE ENERGIA", title_style))
    story.append(Paragraph("E-LUMIA | Hub Solution Intelligence", subtitle_style))
    
    if nome_cliente or cnpj_input:
        story.append(Paragraph(f"<b>Target Client:</b> {nome_cliente} (CNPJ: {cnpj_input})", bold_style))
        story.append(Spacer(1, 5))

    # Tabela 1: Nova Matriz Global de Fornecedores no PDF
    story.append(Paragraph("1. Matriz Global de Ofertas Computadas (Anual)", h2_style))
    pdf_global_matrix_data = [["Fornecedor", "Ano 1", "Ano 2", "Ano 3", "Ano 4", "Ano 5"]]
    for row in linhas_matriz_global:
        pdf_global_matrix_data.append([
            row["Comercializadora Mapeada"],
            f"R$ {row['Ano 1 (R$/MWh)']:,.2f}", f"R$ {row['Ano 2 (R$/MWh)']:,.2f}",
            f"R$ {row['Ano 3 (R$/MWh)']:,.2f}", f"R$ {row['Ano 4 (R$/MWh)']:,.2f}",
            f"R$ {row['Ano 5 (R$/MWh)']:,.2f}"
        ])
    t_global = Table(pdf_global_matrix_data, colWidths=[132, 84, 84, 84, 84, 84])
    t_global.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1A365D")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('FONTSIZE', (0,0), (-1,-1), 8),
    ]))
    story.append(t_global)

    # Tabela 2: Cenário Mensal Comparativo
    story.append(Paragraph("2. Engenharia de Distribuição Mensal (Ano 1)", h2_style))
    pdf_fatura_data = [
        ["Estrutura de Custo", "Cenário Cativo", f"Cenário Livre ({melhor_com_mes})"],
        ["Faturamento Distribuidora Fio", f"R$ {(total_demanda_cat+total_tusd_p_cat+total_tusd_fp_cat):,.2f}", f"R$ {fatura_residual_concessionaria_acl:,.2f}"],
        ["Contrato Consumo Energia", "-", f"R$ {dados_melhor['fatura_energia']:,.2f}"],
        ["Gestão Hub E-Lumia", "-", f"R$ {total_gestao_elumia_mes:,.2f}"],
        ["Custo de Desembolso Total", f"R$ {fatura_mensal_cativa:,.2f}", f"R$ {dados_melhor['custo_total_acl']:,.2f}"]
    ]
    t_fatura = Table(pdf_fatura_data, colWidths=[200, 170, 182])
    t_fatura.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1A365D")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#F8FAFC")),
    ]))
    story.append(t_fatura)

    # Tabela 3: Estudo Cronológico Viabilidade
    story.append(Paragraph("3. Curva Cronológica de Viabilidade Macroeconômica", h2_style))
    proj_data = [["Período", "Projeção Cativo", "Projeção Otimizada ACL", "Economia Gerada"]]
    for row in linhas_proj:
        proj_data.append([
            row["Período"], f"R$ {row['Custo Projetado no Cativo']:,.2f}",
            f"R$ {row[f'Custo Otimizado ACL ({melhor_com_mes})']:,.2f}", f"R$ {row['Economia Financeira no Ano']:,.2f}"
        ])
    proj_data.append(["ACUMULADO CONTRATUAL", f"R$ {custo_cativo_acumulado_total:,.2f}", f"R$ {custo_livre_acumulado_total:,.2f}", f"R$ {(custo_cativo_acumulado_total - custo_livre_acumulado_total):,.2f}"])
    
    t_proj = Table(proj_data, colWidths=[140, 130, 130, 152])
    t_proj.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1A365D")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#16A34A")),
        ('TEXTCOLOR', (0,-1), (-1,-1), colors.whitesmoke),
    ]))
    story.append(t_proj)

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

pdf_bytes = build_pdf()

# --- AUTOMAÇÃO INTELIGENTE DE BACKGROUND UPLOAD (GOOGLE DRIVE API) ---
def upload_automatico_drive(data_bytes, name_file):
    try:
        # Puxa a chave JSON da Service Account direto da infra do Streamlit Cloud Secrets
        info_keys = st.secrets["gdrive_credentials"]
        folder_target_id = st.secrets["gdrive_folder_id"]
        
        credentials_account = service_account.Credentials.from_service_account_info(info_keys)
        service_drive = build('drive', 'v3', credentials=credentials_account)
        
        meta_data = {'name': name_file, 'parents': [folder_target_id]}
        stream_media = MediaIoBaseUpload(BytesIO(data_bytes), mimetype='application/pdf', resumable=True)
        
        # Executa a gravação na nuvem
       # Executa a gravação na nuvem (agora com suporte a Drives Compartilhados)
        service_drive.files().create(
            body=meta_data, 
            media_body=stream_media, 
            fields='id',
            supportsAllDrives=True
        ).execute()
        return True
    except Exception as error_log:
        # Não trava o app na tela caso falte configurar as credenciais secretas
        return str(error_log)

# ALGORITMO DE MONITORAMENTO (HASH TRACKER DE INPUTS)
string_inputs_comerciais = f"{cnpj_limpo}-{nome_cliente}-{demanda_contratada}-{consumo_kwh_fp}-{str(dados_precos)}"
hash_estado_atual = hashlib.md5(string_inputs_comerciais.encode()).hexdigest()

if "last_uploaded_state_hash" not in st.session_state:
    st.session_state.last_uploaded_state_hash = ""

# Condicional de Estabilidade: Só envia se for uma simulação preenchida inédita
if hash_estado_atual != st.session_state.last_uploaded_state_hash and len(cnpj_limpo) == 14:
    nome_arquivamento_drive = f"AutoSave_Proposta_{nome_cliente.replace(' ', '_')}_{hash_estado_atual[:6]}.pdf"
    status_upload = upload_automatico_drive(pdf_bytes, nome_arquivamento_drive)
    
    if status_upload is True:
        st.sidebar.success(f"💾 Cópia de Segurança arquivada automaticamente no Google Drive!")
        st.session_state.last_uploaded_state_hash = hash_estado_atual
    else:
        # AGORA ELE VAI MOSTRAR O ERRO REAL EM VERMELHO!
        st.sidebar.error(f"Erro ao salvar no Drive: {status_upload}")
# CENTRAL DE DOWNLOAD MANUAL DO USUÁRIO
st.markdown("---")
st.subheader("🖨️ Central de Fechamento de Propostas")
nome_arquivo_manual = f"Estudo_Viabilidade_{nome_cliente.replace(' ', '_')}.pdf" if nome_cliente else "Estudo_Viabilidade_ELumia.pdf"
st.download_button(
    label="📄 Baixar Proposta Executiva Comercial (PDF)",
    data=pdf_bytes,
    file_name=nome_arquivo_manual,
    mime="application/pdf"
)
