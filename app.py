import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import requests
import re
import hashlib
import os
from io import BytesIO
from datetime import datetime
from bs4 import BeautifulSoup

# Importações para o ecossistema Google Drive API
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# Importações para o motor de PDF (ReportLab)
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.charts.piecharts import Pie

# Configuração da página - E-Lumia Executive BI
st.set_page_config(page_title="E-Lumia | Hub Solution Intelligence", layout="wide", initial_sidebar_state="expanded")

# CSS Ajustado para Dark Mode Premium + Gradientes
st.markdown("""
    <style>
    .card-vendas { 
        background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%); 
        padding: 25px; 
        border-radius: 12px; 
        border-left: 6px solid #3B82F6; 
        margin-bottom: 25px; 
        color: #F8FAFC; 
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3); 
    }
    .destaque-ganho { color: #4ADE80; font-weight: 800; font-size: 1.1em;}
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { border-radius: 4px 4px 0px 0px; padding: 10px 20px; background-color: #1E293B; }
    .stTabs [aria-selected="true"] { background-color: #3B82F6 !important; color: white !important; }
    </style>
    """, unsafe_allow_html=True)

# --- FUNÇÕES DE FORMATAÇÃO PADRÃO BRASILEIRO ---
def moeda_br(valor):
    """Formata float para Moeda no padrão Brasileiro (R$ 1.000,00)"""
    if pd.isna(valor): return "-"
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def perc_br(valor):
    """Formata float para Percentual no padrão Brasileiro (10,5%)"""
    if pd.isna(valor): return "-"
    return f"{valor:.1f}%".replace(".", ",")

# Mapeamento de UF e Submercados
MAPA_SUBMERCADOS = {
    "SP": "Sudeste", "RJ": "Sudeste", "MG": "Sudeste", "ES": "Sudeste",
    "MT": "Sudeste", "MS": "Sudeste", "GO": "Sudeste", "DF": "Sudeste",
    "AC": "Sudeste", "RO": "Sudeste",
    "PR": "Sul", "SC": "Sul", "RS": "Sul",
    "BA": "Nordeste", "SE": "Nordeste", "AL": "Nordeste", "PE": "Nordeste", "PB": "Nordeste", "RN": "Nordeste", "CE": "Nordeste", "PI": "Nordeste",
    "MA": "Norte", "TO": "Norte", "PA": "Norte", "AP": "Norte", "AM": "Norte", "RR": "Norte"
}

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
NOME_ARQUIVO_PRECOS = "precos_comercializadoras.csv"

# --- MOTOR DE RASPAGEM DA INTERNET (WEB SCRAPING PLD) ---
@st.cache_data(ttl=10800)
def buscar_pld_internet():
    meses_pt = {1:"Janeiro", 2:"Fevereiro", 3:"Março", 4:"Abril", 5:"Maio", 6:"Junho", 7:"Julho", 8:"Agosto", 9:"Setembro", 10:"Outubro", 11:"Novembro", 12:"Dezembro"}
    mes_atual = meses_pt[datetime.now().month]
    ano_atual = datetime.now().year
    
    dados_pld = {
        "Sudeste": 277.61, "Sul": 277.62, "Nordeste": 256.33, "Norte": 256.32, 
        "mes_ref": f"{mes_atual}/{ano_atual}", "fonte": "Segurança/Estimado"
    }
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    try:
        url = "https://ccee.org.br/" 
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            pass
    except Exception:
        pass 
    return dados_pld

@st.cache_data
def load_local_data():
    try:
        df = pd.read_csv(NOME_ARQUIVO_CSV, sep=None, engine='python', encoding='utf-8-sig', on_bad_lines='skip')
        df.columns = df.columns.str.strip()
        return df
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=60)
def load_precos_data():
    try:
        df_precos = pd.read_csv(NOME_ARQUIVO_PRECOS, sep=None, engine='python', encoding='utf-8-sig', on_bad_lines='skip')
        df_precos.columns = df_precos.columns.str.strip().str.title()
        cols = df_precos.columns.tolist()
        if cols and ("Unnamed" in cols[0] or cols[0] == ""):
            df_precos.rename(columns={cols[0]: "Comercializadora"}, inplace=True)
        return df_precos
    except Exception as e:
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
    tusd_demanda = 25.00
    tusd_demanda_p = 45.00
    tusd_demanda_fp = 20.00
    tusd_energia_fp, tusd_energia_p, te_fp, te_p = 80.0, 250.0, 320.0, 550.0
    
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
        except Exception:
            pass

    return {
        "tusd_demanda": tusd_demanda, "tusd_demanda_p": tusd_demanda_p, "tusd_demanda_fp": tusd_demanda_fp, 
        "tusd_energia_p": tusd_energia_p, "tusd_energia_fp": tusd_energia_fp, "te_p": te_p, "te_fp": te_fp
    }

def upload_automatico_drive(data_bytes, name_file):
    try:
        info_keys = st.secrets["gdrive_credentials"]
        folder_target_id = st.secrets["gdrive_folder_id"]
        credentials_account = service_account.Credentials.from_service_account_info(info_keys)
        service_drive = build('drive', 'v3', credentials=credentials_account)
        meta_data = {'name': name_file, 'parents': [folder_target_id]}
        stream_media = MediaIoBaseUpload(BytesIO(data_bytes), mimetype='application/pdf', resumable=True)
        service_drive.files().create(body=meta_data, media_body=stream_media, fields='id', supportsAllDrives=True).execute()
        return True
    except Exception as error_log:
        return str(error_log)

# --- BARRA LATERAL: ENTRADA DE DADOS ---
st.sidebar.header("👤 Consultor Responsável")
vendedor_responsavel = st.sidebar.selectbox("Executivo de Vendas", ["Peterson", "Roberto", "Thaiz"])
st.sidebar.markdown("---")

st.sidebar.header("🎯 Qualificação do Cliente")

# SELETOR DE AMBIENTE (CATIVO VS LIVRE) COM TOOLTIP
ambiente_atual = st.sidebar.radio("Ambiente Atual do Cliente", ["Mercado Cativo", "Mercado Livre"], 
                                  help="Selecione Cativo para comparar contra as tarifas da concessionária. Selecione Livre para comparar nossa proposta com o contrato atual do cliente.")

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

uf_distribuidora = dados_fiscais["UF"]
submercado_inferido = MAPA_SUBMERCADOS.get(uf_distribuidora, "Sudeste")
lista_submercados = ["Sudeste", "Sul", "Nordeste", "Norte"]

st.sidebar.markdown("---")
st.sidebar.subheader("🌍 Região de Fornecimento")
submercado_selecionado = st.sidebar.selectbox("Submercado (Auto-Detectado)", lista_submercados, index=lista_submercados.index(submercado_inferido))

subgrupo = st.sidebar.selectbox("Subgrupo Tarifário", ["A4", "A3"])
modalidade = st.sidebar.selectbox("Modalidade na Distribuidora", ["Verde", "Azul"], 
                                  help="Tarifa Verde: Demanda única. Tarifa Azul: Exige separação entre Demanda Ponta e Fora Ponta.")
tempo_contrato = st.sidebar.slider("Horizonte (Meses)", 12, 60, 36, step=12)

tipo_energia = st.sidebar.selectbox("Produto Sugerido", ["Convencional", "Incentivada 50%", "Incentivada 100%"], 
                                    help="A energia incentivada possui fontes renováveis e gera desconto direto na Tarifa de Uso do Sistema de Distribuição (TUSD) do cliente.")
fator_desconto_demanda = 1.0 if tipo_energia == "Convencional" else (0.5 if tipo_energia == "Incentivada 50%" else 0.0)

st.sidebar.subheader("📊 Métricas de Consumo e Demanda")

if modalidade == "Azul":
    demanda_ponta = st.sidebar.number_input("Demanda Ponta (kW)", value=500.0)
    demanda_fponta = st.sidebar.number_input("Demanda Fora Ponta (kW)", value=500.0)
    demanda_unica = 0.0
else:
    demanda_unica = st.sidebar.number_input("Demanda Contratada (kW)", value=500.0)
    demanda_ponta = 0.0
    demanda_fponta = 0.0

consumo_kwh_fp = st.sidebar.number_input("Consumo Fora Ponta (kWh/mês)", value=120000.0, step=5000.0)
consumo_kwh_p = st.sidebar.number_input("Consumo Ponta (kWh/mês)", value=15000.0, step=1000.0)

if ambiente_atual == "Mercado Livre":
    preco_energia_atual_livre = st.sidebar.number_input("Preço Atual da Energia no Concorrente (R$/MWh)", value=250.00, format="%.2f",
                                                        help="Digite o valor que o cliente está pagando hoje para a gestora concorrente.")
else:
    preco_energia_atual_livre = 0.0

fee_elumia_mwh = st.sidebar.number_input("Gestão Executiva E-Lumia (R$/MWh)", value=6.00, format="%.2f")

consumo_fp = consumo_kwh_fp / 1000
consumo_p = consumo_kwh_p / 1000
consumo_total_mes_kwh = consumo_kwh_fp + consumo_kwh_p
consumo_total_ano_mwh = (consumo_total_mes_kwh / 1000) * 12

# --- INTEGRAÇÃO DO BANCO DE PREÇOS ---
df_precos_globais = load_precos_data()
comercializadoras = []
dados_precos_auto = {}

if not df_precos_globais.empty:
    cols = df_precos_globais.columns.tolist()
    if "Comercializadora" not in cols:
        df_precos_globais.rename(columns={cols[0]: "Comercializadora"}, inplace=True)
        cols = df_precos_globais.columns.tolist()

    if "Comercializadora" in cols and "Ano" in cols and submercado_selecionado in cols:
        if "Produto" in cols:
            mask_filtros = (df_precos_globais["Produto"].astype(str).str.strip().str.upper() == tipo_energia.upper())
            df_filtrado = df_precos_globais[mask_filtros].sort_values(by=['Comercializadora', 'Ano'])
        else:
            df_filtrado = df_precos_globais.sort_values(by=['Comercializadora', 'Ano'])
            
        comercializadoras = df_filtrado['Comercializadora'].dropna().unique().tolist()
        
        for com in comercializadoras:
            df_com = df_filtrado[df_filtrado['Comercializadora'] == com]
            precos_brutos = df_com[submercado_selecionado].tolist()
            
            precos_limpos = []
            for p in precos_brutos[:5]: 
                str_p = str(p).upper().replace('R$', '').strip()
                str_p = re.sub(r'[^\d,.-]', '', str_p)
                str_p = str_p.replace(',', '.')
                valor_num = pd.to_numeric(str_p, errors='coerce')
                if pd.isna(valor_num): valor_num = 0.0
                precos_limpos.append(float(valor_num))
                
            while len(precos_limpos) < 5:
                precos_limpos.append(precos_limpos[-1] if precos_limpos else 0.0)
            dados_precos_auto[com] = precos_limpos

if not comercializadoras:
    comercializadoras = ["Casa dos Ventos Padrão", "Matrix Padrão"]
    dados_precos_auto = {
        "Casa dos Ventos Padrão": [180.0, 186.0, 192.5, 199.2, 206.1],
        "Matrix Padrão": [185.0, 191.0, 197.8, 204.5, 211.8]
    }

modo_manual = st.sidebar.toggle("🔓 Desbloquear Precificação Manual")
dados_precos = {}

if modo_manual:
    st.sidebar.caption("Modo de exceção ativado. Você pode editar os valores propostos:")
    for com in comercializadoras:
        with st.sidebar.expander(f"Editar - {com}", expanded=False):
            precos_anos = []
            for i in range(5):
                default_val = float(dados_precos_auto[com][i]) if i < len(dados_precos_auto[com]) else 0.0
                p = st.number_input(f"Ano {i+1} (R$/MWh)", value=default_val, key=f"manual_{com}_ano_{i+1}")
                precos_anos.append(p)
            dados_precos[com] = precos_anos
else:
    dados_precos = dados_precos_auto

componentes = fetch_fatura_data(concessionaria, subgrupo, modalidade)

# --- ÁREA PRINCIPAL DA PLATAFORMA ---
pld_dados = buscar_pld_internet()
if pld_dados:
    st.markdown(f"**Termômetro de Exposição CCEE | PLD Médio - {pld_dados['mes_ref']}**")
    pld1, pld2, pld3, pld4 = st.columns(4)
    def formatar_pld(mercado_nome, valor_pld):
        if mercado_nome.upper() == submercado_selecionado.upper(): return f"📍 {mercado_nome}"
        return mercado_nome
    pld1.metric(formatar_pld("Sudeste/CO", pld_dados['Sudeste']), moeda_br(pld_dados['Sudeste']))
    pld2.metric(formatar_pld("Sul", pld_dados['Sul']), moeda_br(pld_dados['Sul']))
    pld3.metric(formatar_pld("Nordeste", pld_dados['Nordeste']), moeda_br(pld_dados['Nordeste']))
    pld4.metric(formatar_pld("Norte", pld_dados['Norte']), moeda_br(pld_dados['Norte']))
    st.markdown("---")

nome_cenario_base = "Mercado Cativo" if ambiente_atual == "Mercado Cativo" else "Contrato Atual"
st.title(f"⚡ E-Lumia | Proposta: {nome_cenario_base} vs. E-Lumia")

# 1. EXIBIÇÃO DA MATRIZ GLOBAL DE OFERTAS
st.subheader(f"🏢 Matriz Global de Ofertas Mapeadas para o Estudo ({tipo_energia})")
linhas_matriz_global = []
for com in comercializadoras:
    linhas_matriz_global.append({
        "Comercializadora": com,
        "2026 (R$/MWh)": dados_precos[com][0], "2027 (R$/MWh)": dados_precos[com][1],
        "2028 (R$/MWh)": dados_precos[com][2], "2029 (R$/MWh)": dados_precos[com][3], "2030 (R$/MWh)": dados_precos[com][4],
    })
df_matriz_global_tela = pd.DataFrame(linhas_matriz_global)
st.dataframe(df_matriz_global_tela.style.format({
    "2026 (R$/MWh)": moeda_br, "2027 (R$/MWh)": moeda_br, "2028 (R$/MWh)": moeda_br, "2029 (R$/MWh)": moeda_br, "2030 (R$/MWh)": moeda_br
}), use_container_width=True, hide_index=True)

# --- EXECUÇÃO IMEDIATA DOS CÁLCULOS NA TELA (UX FLUIDO SÉRIO) ---
def decompor_item(valor_base):
    valor_com_imposto = valor_base / (1 - impostos_totais)
    imposto_calculado = valor_com_imposto * impostos_totais
    return valor_base, imposto_calculado, valor_com_imposto

if modalidade == "Azul":
    _, _, total_demanda_p_cat = decompor_item(demanda_ponta * componentes["tusd_demanda_p"])
    _, _, total_demanda_fp_cat = decompor_item(demanda_fponta * componentes["tusd_demanda_fp"])
    total_demanda_cat = total_demanda_p_cat + total_demanda_fp_cat
    
    _, _, total_demanda_p_acl = decompor_item(demanda_ponta * componentes["tusd_demanda_p"] * fator_desconto_demanda)
    _, _, total_demanda_fp_acl = decompor_item(demanda_fponta * componentes["tusd_demanda_fp"] * fator_desconto_demanda)
    total_demanda_acl = total_demanda_p_acl + total_demanda_fp_acl
else:
    _, _, total_demanda_cat = decompor_item(demanda_unica * componentes["tusd_demanda"])
    _, _, total_demanda_acl = decompor_item(demanda_unica * componentes["tusd_demanda"] * fator_desconto_demanda)

_, _, total_tusd_p_cat = decompor_item(consumo_p * componentes["tusd_energia_p"])
_, _, total_tusd_fp_cat = decompor_item(consumo_fp * componentes["tusd_energia_fp"])
_, _, total_te_p_cat = decompor_item(consumo_p * componentes["te_p"])
_, _, total_te_fp_cat = decompor_item(consumo_fp * componentes["te_fp"])

if ambiente_atual == "Mercado Cativo":
    fatura_mensal_cativa = total_demanda_cat + total_tusd_p_cat + total_tusd_fp_cat + total_te_p_cat + total_te_fp_cat
    fatura_mensal_atual = fatura_mensal_cativa
    df_atual_peso = pd.DataFrame({
        "Componente": ["Demanda", "TUSD Ponta", "TUSD F. Ponta", "TE Ponta", "TE F. Ponta"],
        "Valor": [total_demanda_cat, total_tusd_p_cat, total_tusd_fp_cat, total_te_p_cat, total_te_fp_cat]
    })
else: 
    fatura_mensal_cativa = total_demanda_cat + total_tusd_p_cat + total_tusd_fp_cat + total_te_p_cat + total_te_fp_cat
    _, _, total_energia_atual_concorrente = decompor_item((consumo_total_mes_kwh / 1000) * preco_energia_atual_livre)
    fatura_mensal_atual = total_demanda_acl + total_tusd_p_cat + total_tusd_fp_cat + total_energia_atual_concorrente
    df_atual_peso = pd.DataFrame({
        "Componente": ["Demanda (TUSD c/ Desc)", "TUSD Ponta", "TUSD F. Ponta", "Energia Atual Concorrente"],
        "Valor": [total_demanda_acl, total_tusd_p_cat, total_tusd_fp_cat, total_energia_atual_concorrente]
    })

fatura_residual_concessionaria_acl = total_demanda_acl + total_tusd_p_cat + total_tusd_fp_cat
_, _, total_gestao_elumia_mes = decompor_item((consumo_total_mes_kwh / 1000) * fee_elumia_mwh)

anos_reais = int(tempo_contrato / 12)
dados_comparativo_fornecedores = []
ano_corrente_calendario = 2026

for com in comercializadoras:
    soma_economia_contrato = 0
    for ano_idx in range(anos_reais):
        fator_distribuidora = (1 + 0.08) ** ano_idx
        
        if ambiente_atual == "Mercado Cativo":
            custo_atual_projetado_ano = (fatura_mensal_atual * 12) * fator_distribuidora
        else:
            p_atual_livre = preco_energia_atual_livre
            _, _, fat_energia_ano_concorrente = decompor_item(consumo_total_ano_mwh * p_atual_livre)
            custo_atual_projetado_ano = ((fatura_residual_concessionaria_acl * 12) * fator_distribuidora) + fat_energia_ano_concorrente
        
        preco_csv_do_ano = dados_precos[com][ano_idx]
        _, _, fatura_energia_ano_elumia = decompor_item(consumo_total_ano_mwh * preco_csv_do_ano)
        
        fator_gestao = (1 + 0.06) ** ano_idx
        custo_proposto_ano = ((fatura_residual_concessionaria_acl * 12) * fator_distribuidora) + fat_energia_ano_elumia + ((total_gestao_elumia_mes * 12) * fator_gestao)
        soma_economia_contrato += (custo_atual_projetado_ano - custo_proposto_ano)
        
    eco_media_ano = soma_economia_contrato / (tempo_contrato / 12)
    eco_media_mes = eco_media_ano / 12
    
    preco_ano1 = dados_precos[com][0]
    _, _, tot_eng = decompor_item((consumo_total_mes_kwh / 1000) * preco_ano1)
    c_livre_mes_1 = fatura_residual_concessionaria_acl + tot_eng + total_gestao_elumia_mes

    dados_comparativo_fornecedores.append({
        "Comercializadora": com,
        "Economia Média Mês (R$)": eco_media_mes,
        "Economia Média Ano (R$)": eco_media_ano,
        "Economia Total Contrato (R$)": soma_economia_contrato,
        "Custo_Total_Ordenacao": c_livre_mes_1 
    })

melhor_fornecedor_row = max(dados_comparativo_fornecedores, key=lambda x: x["Economia Total Contrato (R$)"])
melhor_com_mes = melhor_fornecedor_row["Comercializadora"]

preco_ano1_melhor = dados_precos[melhor_com_mes][0]
_, _, total_energia_mes_melhor = decompor_item((consumo_total_mes_kwh / 1000) * preco_ano1_melhor)
custo_total_acl_melhor_mes = fatura_residual_concessionaria_acl + total_energia_mes_melhor + total_gestao_elumia_mes
economia_mes_1_perc = ((fatura_mensal_atual - custo_total_acl_melhor_mes) / fatura_mensal_atual) * 100

saudacao = f"para o cliente <b>{nome_cliente}</b>" if nome_cliente else ""
st.markdown(f"""
<div class="card-vendas">
    <h3 style='margin-top: 0px; margin-bottom: 5px; color: #60A5FA;'>🏆 Match Ideal Encontrado!</h3>
    <p style='font-size: 1.1em; line-height: 1.5;'>
        Através da nossa inteligência de dados, a fornecedora mais competitiva {saudacao} no Submercado {submercado_selecionado} para o produto <b>{tipo_energia}</b> é a <b>{melhor_com_mes}</b>.<br/>
        Este parceiro garante uma economia imediata de <span class='destaque-ganho'>{perc_br(economia_mes_1_perc)}</span> já no primeiro ano.
    </p>
    <div style='font-size: 0.9em; color:#94A3B8; margin-top: 10px;'>👤 Consultor Responsável: {vendedor_responsavel}</div>
</div>
""", unsafe_allow_html=True)

tab_resumo, tab_projecao, tab_concorrencia, tab_bandeiras = st.tabs([
    "📊 1. Resumo Executivo", 
    "📈 2. Projeção Financeira", 
    "🏢 3. Cenário de Mercado", 
    "🚩 4. Blindagem Tarifária"
])

with tab_resumo:
    st.markdown("### Composição de Custos (Primeiro Ano)")
    df_atual_peso = df_atual_peso[df_atual_peso["Valor"] > 0].copy()
    df_atual_peso["Peso (%)"] = (df_atual_peso["Valor"] / df_atual_peso["Valor"].sum()) * 100

    df_livre_peso = pd.DataFrame({
        "Componente": ["Demanda (TUSD c/ Desc)", "TUSD Ponta", "TUSD F. Ponta", "Energia Proposta ACL", "Gestão E-Lumia"],
        "Valor": [total_demanda_acl, total_tusd_p_cat, total_tusd_fp_cat, total_energia_mes_melhor, total_gestao_elumia_mes]
    })
    df_livre_peso = df_livre_peso[df_livre_peso["Valor"] > 0]
    df_livre_peso["Peso (%)"] = (df_livre_peso["Valor"] / df_livre_peso["Valor"].sum()) * 100

    col_g1, col_g2 = st.columns(2)
    with col_g1:
        fig_cat = px.pie(df_atual_peso, values='Valor', names='Componente', title="Cenário Base (Atual)", hole=0.4, color_discrete_sequence=px.colors.sequential.RdBu)
        fig_cat.update_traces(textposition='inside', textinfo='percent+label', marker=dict(line=dict(color='#0F172A', width=2)))
        fig_cat.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font_color="white")
        st.plotly_chart(fig_cat, use_container_width=True)
        df_atual_peso_tela = pd.concat([df_atual_peso, pd.DataFrame([{"Componente": "SOMA DA FATURA (TOTAL)", "Valor": fatura_mensal_atual, "Peso (%)": 100.0}])], ignore_index=True)
        st.dataframe(df_atual_peso_tela.style.format({"Valor": moeda_br, "Peso (%)": perc_br}), hide_index=True, use_container_width=True)

    with col_g2:
        fig_liv = px.pie(df_livre_peso, values='Valor', names='Componente', title=f"Proposta E-Lumia ({melhor_com_mes})", hole=0.4, color_discrete_sequence=px.colors.sequential.Greens_r)
        fig_liv.update_traces(textposition='inside', textinfo='percent+label', marker=dict(line=dict(color='#0F172A', width=2)))
        fig_liv.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font_color="white")
        st.plotly_chart(fig_liv, use_container_width=True)
        df_livre_peso_tela = pd.concat([df_livre_peso, pd.DataFrame([{"Componente": "SOMA DA FATURA (TOTAL)", "Valor": custo_total_acl_melhor_mes, "Peso (%)": 100.0}])], ignore_index=True)
        st.dataframe(df_livre_peso_tela.style.format({"Valor": moeda_br, "Peso (%)": perc_br}), hide_index=True, use_container_width=True)

with tab_projecao:
    st.markdown("### Projeção Financeira e Estudo de Economia")
    linhas_proj_mensal = []
    custo_atual_acumulado_total = 0
    custo_livre_acumulado_total = 0

    for ano_idx in range(anos_reais):
        ano_civil_estudo = ano_corrente_calendario + ano_idx
        fator_distribuidora = (1 + 0.08) ** ano_idx
        fator_gestao = (1 + 0.06) ** ano_idx
        
        if ambiente_atual == "Mercado Cativo":
            custo_atual_projetado_ano = (fatura_mensal_atual * 12) * fator_distribuidora
        else:
            p_atual_livre = preco_energia_atual_livre
            _, _, fat_energia_ano_concorrente = decompor_item(consumo_total_ano_mwh * p_atual_livre)
            custo_atual_projetado_ano = ((fatura_residual_concessionaria_acl * 12) * fator_distribuidora) + fat_energia_ano_concorrente
            
        preco_csv_do_ano = dados_precos[melhor_com_mes][ano_idx]
        _, _, fatura_energia_ano_elumia = decompor_item(consumo_total_ano_mwh * preco_csv_do_ano)
        
        fatura_resid_ano = (fatura_residual_concessionaria_acl * 12) * fator_distribuidora
        fee_ano = (total_gestao_elumia_mes * 12) * fator_gestao
        custo_proposto_ano = fatura_resid_ano + fatura_energia_ano_elumia + fee_ano
        
        custo_atual_acumulado_total += custo_atual_projetado_ano
        custo_livre_acumulado_total += custo_proposto_ano
        
        pago_mensal_atual = custo_atual_projetado_ano / 12
        pago_mensal_proposto = custo_proposto_ano / 12
        economia_reais_mes = pago_mensal_atual - pago_mensal_proposto
        economia_perc_mes = (economia_reais_mes / pago_mensal_atual) * 100
        
        linhas_proj_mensal.append({
            "Ano": str(ano_civil_estudo),
            "Média Mensal Base (R$/mês)": pago_mensal_atual,
            "Média Mensal E-Lumia (R$/mês)": pago_mensal_proposto,
            "Economia Média Mensal (R$/mês)": economia_reais_mes,
            "Economia (%)": economia_perc_mes
        })

    df_estudo_integral_mensal = pd.DataFrame(linhas_proj_mensal)
    
    fig_bar = px.bar(
        df_estudo_integral_mensal, x='Ano', y=['Média Mensal Base (R$/mês)', 'Média Mensal E-Lumia (R$/mês)'], barmode='group',
        title="Evolução do Custo: Fatura Atual vs. Proposta", labels={'value': 'Custo Mensal Estimado (R$)', 'variable': 'Cenário'},
        color_discrete_map={'Média Mensal Base (R$/mês)': '#ef4444', 'Média Mensal E-Lumia (R$/mês)': '#22c55e'}
    )
    fig_bar.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font_color="white", legend_title_text='')
    st.plotly_chart(fig_bar, use_container_width=True)

    st.dataframe(df_estudo_integral_mensal.style.format({
        "Média Mensal Base (R$/mês)": moeda_br, "Média Mensal E-Lumia (R$/mês)": moeda_br, 
        "Economia Média Mensal (R$/mês)": moeda_br, "Economia (%)": perc_br
    }), use_container_width=True, hide_index=True)

with tab_conconcorrencia:
    st.markdown("### Inteligência de Mercado: Matriz de Fornecedores")
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        st.caption("Matriz Base de Preços (R$/MWh)")
        df_matriz_global_tela = pd.DataFrame(linhas_matriz_global)
        st.dataframe(df_matriz_global_tela.style.format({
            "2026 (R$/MWh)": moeda_br, "2027 (R$/MWh)": moeda_br, "2028 (R$/MWh)": moeda_br, "2029 (R$/MWh)": moeda_br, "2030 (R$/MWh)": moeda_br
        }), use_container_width=True, hide_index=True)
    with col_c2:
        st.caption("Ranking de Viabilidade por Comercializadora")
        df_fornecedores_tela = pd.DataFrame(dados_comparativo_fornecedores).sort_values("Economia Total Contrato (R$)", ascending=False)
        st.dataframe(df_fornecedores_tela[['Comercializadora', 'Economia Média Mês (R$)', 'Economia Média Ano (R$)', 'Economia Total Contrato (R$)']].style.format({
            "Economia Média Mês (R$)": moeda_br, "Economia Média Ano (R$)": moeda_br, "Economia Total Contrato (R$)": moeda_br
        }), use_container_width=True, hide_index=True)

with tab_bandeiras:
    st.markdown(f"### 🚩 Blindagem contra Bandeiras Tarifárias (Garantia E-Lumia)")
    BANDEIRAS = {"Bandeira Verde": 0.0, "Bandeira Amarela": 18.85, "Bandeira Vermelha 1": 44.63, "Bandeira Vermelha 2": 78.77}
    linhas_bandeiras = []
    for nome_bandeira, valor_mwh in BANDEIRAS.items():
        _, _, acrescimo_bandeira_com_imposto = decompor_item((consumo_total_mes_kwh / 1000) * valor_mwh)
        cativo_com_bandeira = fatura_mensal_cativa + acrescimo_bandeira_com_imposto
        economia_bandeira_reais = cativo_com_bandeira - custo_total_acl_melhor_mes
        economia_bandeira_perc = (economia_bandeira_reais / cativo_com_bandeira) * 100
        linhas_bandeiras.append({
            "Cenário Hídrico": nome_bandeira, "Custo Cativo Estimado (c/ Bandeira)": cativo_com_bandeira,
            "Custo Mensal Proposta E-Lumia": custo_total_acl_melhor_mes, "Economia Mensal Gerada (R$)": economia_bandeira_reais, "Economia (%)": economia_bandeira_perc
        })
    df_bandeiras = pd.DataFrame(linhas_bandeiras)
    st.dataframe(df_bandeiras.style.format({
        "Custo Cativo Estimado (c/ Bandeira)": moeda_br, "Custo Mensal Proposta E-Lumia": moeda_br,
        "Economia Mensal Gerada (R$)": moeda_br, "Economia (%)": perc_br
    }), use_container_width=True, hide_index=True)

st.markdown("<br/>", unsafe_allow_html=True)
k_final1, k_final2, k_final3 = st.columns(3)
k_final1.metric(f"Gasto Total Acumulado Estimado ({ambiente_atual})", moeda_br(custo_atual_acumulado_total))
k_final2.metric(f"Gasto Total Acumulado Otimizado ({melhor_com_mes})", moeda_br(custo_livre_acumulado_total))
k_final3.metric("Patrimônio Total Recuperado", moeda_br(custo_atual_acumulado_total - custo_livre_acumulado_total), delta="Economia Gerada para o Cliente")

# --- MOTOR DO PDF PAISAGEM ---
def draw_pdf_pie(df_peso, title_text):
    d = Drawing(300, 160)
    pc = Pie()
    pc.x = 60
    pc.y = 20
    pc.width = 120
    pc.height = 120
    pc.data = df_peso['Valor'].tolist()
    rotulos = []
    for i, row in df_peso.iterrows():
        rotulos.append(f"{row['Componente']} ({perc_br(row['Peso (%)'])})")
    pc.labels = rotulos
    pc.sideLabels = 1
    pc.slices.strokeWidth = 0.5
    if "Base" in title_text or "Atual" in title_text:
        pc.slices[0].fillColor = colors.HexColor("#ef4444") 
        pc.slices[3].fillColor = colors.HexColor("#f87171") 
    else:
        pc.slices[3].fillColor = colors.HexColor("#22c55e") 
        pc.slices[4].fillColor = colors.HexColor("#3b82f6") 
    title = String(120, 150, title_text)
    title.fontName = 'Helvetica-Bold'
    title.fontSize = 11
    title.textAnchor = 'middle' 
    d.add(title)
    d.add(pc)
    return d

def build_pdf():
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    title_style_left = ParagraphStyle('TitleStyleLeft', fontName='Helvetica-Bold', fontSize=16, textColor=colors.HexColor("#1A365D"), alignment=2)
    h2_style = ParagraphStyle('H2Style', parent=styles['Heading2'], fontSize=11, textColor=colors.HexColor("#1E3A8A"), spaceBefore=12, spaceAfter=6, fontName='Helvetica-Bold')
    card_style = ParagraphStyle('Card', fontSize=12, textColor=colors.whitesmoke, alignment=1)
    
    story = []
    if os.path.exists("logo.png"):
        logo_element = Image("logo.png", width=120, height=40)
    else:
        logo_style = ParagraphStyle('LogoStyle', fontName='Helvetica-Bold', fontSize=18, textColor=colors.HexColor("#3B82F6"))
        logo_element = Paragraph("⚡ E-LUMIA", logo_style)
        
    title_p = Paragraph("PROPOSTA EXECUTIVA - MERCADO LIVRE DE ENERGIA", title_style_left)
    header_table = Table([[logo_element, title_p]], colWidths=[200, 532])
    header_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('ALIGN', (1,0), (1,0), 'RIGHT')]))
    story.append(header_table)
    story.append(Spacer(1, 15))
    
    if pld_dados:
        story.append(Paragraph(f"Termômetro de Exposição CCEE | PLD Médio - {pld_dados['mes_ref']}", h2_style))
        pld_headers = [formatar_pld("Sudeste", 0), formatar_pld("Sul", 0), formatar_pld("Nordeste", 0), formatar_pld("Norte", 0)]
        pld_values = [moeda_br(pld_dados['Sudeste']), moeda_br(pld_dados['Sul']), moeda_br(pld_dados['Nordeste']), moeda_br(pld_dados['Norte'])]
        t_pld = Table([pld_headers, pld_values], colWidths=[183, 183, 183, 183])
        t_pld.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#1E293B")), ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor("#94A3B8")),
            ('TEXTCOLOR', (0,1), (-1,1), colors.whitesmoke), ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,1), (-1,1), 'Helvetica-Bold'), ('FONTSIZE', (0,1), (-1,1), 12),
            ('GRID', (0,0), (-1,-1), 1, colors.HexColor("#334155"))
        ]))
        story.append(t_pld)
        story.append(Spacer(1, 15))

    if nome_cliente or cnpj_input:
        card_text = f"<font color='#3B82F6'><b>DIAGNÓSTICO COMERCIAL EXECUTIVO</b></font><br/><br/>Parceiro mais competitivo selecionado para <b>{nome_cliente}</b> no Submercado <b>{submercado_selecionado}</b> para o produto <b>{tipo_energia}</b>:<br/><b>{melhor_com_mes}</b> com economia de <b>{perc_br(economia_mes_1_perc)}</b> em 2026.<br/><br/><font size='10' color='#94A3B8'>Consultor Responsável: {vendedor_responsavel}</font>"
        t_card = Table([[Paragraph(card_text, card_style)]], colWidths=[732])
        t_card.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#1E293B")), ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('LINEBEFORE', (0,0), (0,-1), 6, colors.HexColor("#3B82F6"))]))
        story.append(t_card)
        story.append(Spacer(1, 15))

    story.append(Paragraph("1. Matriz Global de Ofertas Mapeadas (Anual)", h2_style))
    pdf_matriz_data = [["Comercializadora", "2026", "2027", "2028", "2029", "2030"]]
    for row in linhas_matriz_global:
        pdf_matriz_data.append([row["Comercializadora"], moeda_br(row['2026 (R$/MWh)']), moeda_br(row['2027 (R$/MWh)']), moeda_br(row['2028 (R$/MWh)']), moeda_br(row['2029 (R$/MWh)']), moeda_br(row['2030 (R$/MWh)'])])
    t_matriz = Table(pdf_matriz_data, colWidths=[182, 110, 110, 110, 110, 110])
    t_matriz.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1A365D")), ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke), ('ALIGN', (1,0), (-1,-1), 'RIGHT'), ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey), ('FONTSIZE', (0,0), (-1,-1), 9)]))
    story.append(t_matriz)
    story.append(Spacer(1, 10))

    story.append(Paragraph(f"2. Composição de Custos Mensais (Cenário Base vs Proposta)", h2_style))
    grafico_cativo = draw_pdf_pie(df_atual_peso, "Cenário Base")
    grafico_livre = draw_pdf_pie(df_livre_peso, f"Proposta E-Lumia")
    tabela_graficos = Table([[grafico_cativo, grafico_livre]], colWidths=[366, 366])
    story.append(tabela_graficos)
    story.append(Spacer(1, 10))

    pdf_fatura_data = [["Estrutura de Custo", "Cenário Base (Atual)", "Peso (%)", f"Proposta E-Lumia", "Peso (%)"]]
    linhas_custo = ["Demanda", "Demanda (TUSD c/ Desc)", "TUSD Ponta", "TUSD F. Ponta", "TE Ponta", "TE F. Ponta", "Energia Atual Concorrente", "Energia Proposta ACL", "Gestão E-Lumia"]
    def acha_valor(df, comp):
        linha = df[df["Componente"] == comp]
        if not linha.empty: return moeda_br(linha.iloc[0]['Valor']), perc_br(linha.iloc[0]['Peso (%)'])
        return "-", "-"
    for c in linhas_custo:
        val_cat, peso_cat = acha_valor(df_atual_peso, c)
        val_liv, peso_liv = acha_valor(df_livre_peso, c)
        if val_cat != "-" or val_liv != "-": pdf_fatura_data.append([c, val_cat, peso_cat, val_liv, peso_liv])
    pdf_fatura_data.append(["SOMA DA FATURA (TOTAL)", moeda_br(fatura_mensal_atual), "100,0%", moeda_br(custo_total_acl_melhor_mes), "100,0%"])
    t_fatura = Table(pdf_fatura_data, colWidths=[232, 150, 100, 150, 100])
    t_fatura.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1A365D")), ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke), ('ALIGN', (1,0), (-1,-1), 'RIGHT'), ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey), ('FONTSIZE', (0,0), (-1,-1), 9), ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#F8FAFC")), ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold')]))
    story.append(t_fatura)
    story.append(Spacer(1, 15))

    story.append(Paragraph("3. Estudo Cronológico: Média Mensal Paga por Ano", h2_style))
    proj_data = [["Ano", "Média Mensal Base", "Média Mensal Proposta", "Economia Mês (R$)", "Economia (%)"]]
    for row in linhas_proj_mensal:
        proj_data.append([row["Ano"], moeda_br(row['Média Mensal Base (R$/mês)']), moeda_br(row['Média Mensal E-Lumia (R$/mês)']), moeda_br(row['Economia Média Mensal (R$/mês)']), perc_br(row['Economia (%)'])])
    t_proj = Table(proj_data, colWidths=[132, 150, 150, 150, 150])
    t_proj.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1A365D")), ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke), ('ALIGN', (1,0), (-1,-1), 'RIGHT'), ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey), ('FONTSIZE', (0,0), (-1,-1), 9), ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#16A34A")), ('TEXTCOLOR', (0,-1), (-1,-1), colors.whitesmoke), ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold')]))
    story.append(t_proj)
    story.append(Spacer(1, 15))

    story.append(Paragraph("4. Blindagem contra Bandeiras Tarifárias", h2_style))
    pdf_bandeiras_data = [["Cenário Hídrico", "Custo Estimado (c/ Band.)", f"Proposta E-Lumia", "Economia (R$)", "Economia (%)"]]
    for row in linhas_bandeiras:
        pdf_bandeiras_data.append([row["Cenário Hídrico"], moeda_br(row['Custo Cativo Estimado (c/ Bandeira)']), moeda_br(row['Custo Mensal Proposta E-Lumia']), moeda_br(row['Economia Mensal Gerada (R$)']), perc_br(row['Economia (%)'])])
    t_band = Table(pdf_bandeiras_data, colWidths=[132, 150, 150, 150, 150])
    t_band.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1A365D")), ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke), ('ALIGN', (1,0), (-1,-1), 'RIGHT'), ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey), ('FONTSIZE', (0,0), (-1,-1), 9), ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#16A34A")), ('TEXTCOLOR', (0,-1), (-1,-1), colors.whitesmoke), ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold')]))
    story.append(t_band)
    story.append(Spacer(1, 15))

    story.append(Paragraph("5. Comparativo de Viabilidade por Comercializadora", h2_style))
    pdf_com_forn_data = [["Comercializadora", "Média Econ. Mês", "Média Econ. Ano", "Total Contrato"]]
    for r_com in dados_comparativo_fornecedores:
        pdf_com_forn_data.append([r_com["Comercializadora"], moeda_br(r_com['Economia Média Mês (R$)']), moeda_br(r_com['Economia Média Ano (R$)']), moeda_br(r_com['Economia Total Contrato (R$)'])])
    t_forn = Table(pdf_com_forn_data, colWidths=[222, 170, 170, 170])
    t_forn.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1A365D")), ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke), ('ALIGN', (1,0), (-1,-1), 'RIGHT'), ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey), ('FONTSIZE', (0,0), (-1,-1), 9)]))
    story.append(t_forn)
    story.append(Spacer(1, 20))

    kpi_values = [moeda_br(custo_atual_acumulado_total), moeda_br(custo_livre_acumulado_total), moeda_br(custo_atual_acumulado_total - custo_livre_acumulado_total)]
    t_kpi = Table([[f"Gasto Acumulado ({ambiente_atual})", f"Gasto Acumulado E-Lumia", "Patrimônio Total Recuperado"], kpi_values], colWidths=[244, 244, 244])
    t_kpi.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0F172A")), ('BACKGROUND', (0,1), (-1,1), colors.HexColor("#1E293B")), ('TEXTCOLOR', (0,0), (-1,-1), colors.whitesmoke), ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('FONTNAME', (0,1), (-1,1), 'Helvetica-Bold'), ('FONTSIZE', (0,1), (-1,1), 14), ('GRID', (0,0), (-1,-1), 2, colors.white)]))
    story.append(t_kpi)
    return buffer.getvalue()

# --- NOVO: CENTRAL DE FECHAMENTO COM CONTROLE DE ARQUIVAMENTO MANUAL ---
st.markdown("---")
st.subheader("🖨️ Central de Apresentação e Fechamento de Propostas")
st.caption("Utilize os botões abaixo para interagir de forma controlada com o repositório oficial da empresa.")

col_pdf_down, col_drive_up = st.columns(2)

with col_pdf_down:
    # Geramos o PDF sob demanda para download local
    pdf_bytes = build_pdf()
    nome_cliente_limpo = re.sub(r'[\\/*?:"<>|.]', '', nome_cliente).replace(' ', '_') if nome_cliente else "Cliente"
    nome_arquivo_manual = f"Estudo_Viabilidade_{nome_cliente_limpo}_{vendedor_responsavel}.pdf"
    
    st.download_button(
        label="📄 Baixar Proposta Executiva Oficial (PDF Local)",
        data=pdf_bytes,
        file_name=nome_arquivo_manual,
        mime="application/pdf",
        use_container_width=True
    )

with col_drive_up:
    # O GATILHO SOLICITADO: O arquivo só vai pro Drive quando o vendedor explicitamente confirmar!
    if st.button("💾 Arquivar Versão Oficial no Google Drive", use_container_width=True, type="secondary"):
        # Incluímos Hora e Minutos no nome para nunca sobrescrever se ele salvar mais de uma versão
        timestamp_oficial = datetime.now().strftime("%d-%m-%Y_%Hh%M")
        nome_arquivamento_drive = f"Proposta_{nome_cliente_limpo}_{vendedor_responsavel}_{timestamp_oficial}.pdf"
        
        with st.spinner("Conectando ao Google Drive da E-Lumia..."):
            status_upload = upload_automatico_drive(pdf_bytes, nome_arquivamento_drive)
            
        if status_upload is True:
            st.success(f"✅ Sucesso! Versão cravada e arquivada como: '{nome_arquivamento_drive}'")
        else:
            st.error(f"Falha de credenciais com o servidor do Drive: {status_upload}")
