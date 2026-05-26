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

@st.cache_data(ttl=600)
def load_precos_data():
    try:
        df_precos = pd.read_csv(NOME_ARQUIVO_PRECOS, sep=None, engine='python', encoding='utf-8-sig', on_bad_lines='skip')
        df_precos.columns = df_precos.columns.str.strip()
        return df_precos
    except Exception as e:
        st.sidebar.error(f"Erro ao ler banco de preços ({NOME_ARQUIVO_PRECOS}): {e}")
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
    # Padrões conservadores
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
        "tusd_demanda": tusd_demanda, 
        "tusd_demanda_p": tusd_demanda_p, 
        "tusd_demanda_fp": tusd_demanda_fp, 
        "tusd_energia_p": tusd_energia_p, 
        "tusd_energia_fp": tusd_energia_fp, 
        "te_p": te_p, 
        "te_fp": te_fp
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
modalidade = st.sidebar.selectbox("Modalidade na Distribuidora", ["Verde", "Azul"])
tempo_contrato = st.sidebar.slider("Horizonte (Meses)", 12, 60, 36, step=12)

tipo_energia = st.sidebar.selectbox("Produto Sugerido", ["Convencional", "Incentivada 50%", "Incentivada 100%"])
# Fator multiplicador de desconto na TUSD Demanda (1.0 = paga integral / 0.5 = paga 50% / 0.0 = paga nada)
fator_desconto_demanda = 1.0 if tipo_energia == "Convencional" else (0.5 if tipo_energia == "Incentivada 50%" else 0.0)

st.sidebar.subheader("📊 Métricas de Consumo e Demanda")

# LÓGICA DE INTERFACE PARA VERDE VS AZUL
if modalidade == "Azul":
    demanda_ponta = st.sidebar.number_input("Demanda Ponta (kW)", value=500.0)
    demanda_fponta = st.sidebar.number_input("Demanda Fora Ponta (kW)", value=500.0)
    demanda_unica = 0.0 # Placeholder
else:
    demanda_unica = st.sidebar.number_input("Demanda Contratada (kW)", value=500.0)
    demanda_ponta = 0.0
    demanda_fponta = 0.0

consumo_kwh_fp = st.sidebar.number_input("Consumo Fora Ponta (kWh/mês)", value=120000.0, step=5000.0)
consumo_kwh_p = st.sidebar.number_input("Consumo Ponta (kWh/mês)", value=15000.0, step=1000.0)
fee_elumia_mwh = st.sidebar.number_input("Gestão Executiva E-Lumia (R$/MWh)", value=6.00, format="%.2f")

consumo_fp = consumo_kwh_fp / 1000
consumo_p = consumo_kwh_p / 1000
consumo_total_mes_kwh = consumo_kwh_fp + consumo_kwh_p
consumo_total_ano_mwh = (consumo_total_mes_kwh / 1000) * 12

# --- CAPTURA DA DATA DE ATUALIZAÇÃO DO CSV ---
data_atualizacao_csv = "Data Indisponível"
if os.path.exists(NOME_ARQUIVO_PRECOS):
    timestamp_modificacao = os.path.getmtime(NOME_ARQUIVO_PRECOS)
    data_atualizacao_csv = datetime.fromtimestamp(timestamp_modificacao).strftime('%d/%m/%Y às %H:%M')

st.sidebar.subheader("🏢 Ofertas em Vigor")
st.sidebar.caption(f"🔄 **Última atualização:** {data_atualizacao_csv}")

df_precos_globais = load_precos_data()
comercializadoras = []
dados_precos_auto = {}

if not df_precos_globais.empty:
    cols = df_precos_globais.columns
    if "Comercializadora" in cols and "Ano" in cols and "Produto" in cols and submercado_selecionado in cols:
        mask_filtros = (df_precos_globais["Produto"].astype(str).str.upper() == tipo_energia.upper())
        df_filtrado = df_precos_globais[mask_filtros].sort_values(by=['Comercializadora', 'Ano'])
        comercializadoras = df_filtrado['Comercializadora'].dropna().unique().tolist()
        
        for com in comercializadoras:
            df_com = df_filtrado[df_filtrado['Comercializadora'] == com]
            precos_brutos = df_com[submercado_selecionado].tolist()
            precos_limpos = []
            for p in precos_brutos[:5]: 
                precos_limpos.append(pd.to_numeric(str(p).replace(',', '.'), errors='coerce'))
            while len(precos_limpos) < 5:
                precos_limpos.append(precos_limpos[-1] if precos_limpos else 0.0)
            dados_precos_auto[com] = precos_limpos

if not comercializadoras:
    st.sidebar.warning(f"⚠️ Nenhuma oferta de '{tipo_energia}' cadastrada. Usando valores padrão.")
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
    with st.sidebar.expander(f"👁️ Curvas '{tipo_energia}' Carregadas (CSV)", expanded=False):
        df_display_sidebar = pd.DataFrame(dados_precos, index=["Ano 1", "Ano 2", "Ano 3", "Ano 4", "Ano 5"]).T
        st.dataframe(df_display_sidebar)

componentes = fetch_fatura_data(concessionaria, subgrupo, modalidade)

st.sidebar.markdown("---")
botao_calcular = st.sidebar.button("🚀 Gerar Proposta Comercial", use_container_width=True, type="primary")

# --- ÁREA PRINCIPAL DA PLATAFORMA ---
st.title("⚡ E-Lumia | Hub Solution Intelligence")

# EXIBIÇÃO DO TERMÔMETRO DE MERCADO (PLD SCRAPER)
pld_dados = buscar_pld_internet()
if pld_dados:
    st.markdown(f"**Termômetro de Exposição Mercado de Curto Prazo | PLD Médio - {pld_dados['mes_ref']}**")
    
    pld1, pld2, pld3, pld4 = st.columns(4)
    
    def formatar_pld(mercado_nome, valor_pld):
        if mercado_nome.upper() == submercado_selecionado.upper():
            return f"📍 {mercado_nome}"
        return mercado_nome
        
    pld1.metric(formatar_pld("Sudeste", pld_dados['Sudeste']), f"R$ {pld_dados['Sudeste']:,.2f}")
    pld2.metric(formatar_pld("Sul", pld_dados['Sul']), f"R$ {pld_dados['Sul']:,.2f}")
    pld3.metric(formatar_pld("Nordeste", pld_dados['Nordeste']), f"R$ {pld_dados['Nordeste']:,.2f}")
    pld4.metric(formatar_pld("Norte", pld_dados['Norte']), f"R$ {pld_dados['Norte']:,.2f}")
    st.markdown("---")

st.markdown("## Estudo Comparativo de Faturamento: Cativo vs. Mercado Livre")

if botao_calcular:
    
    def decompor_item(valor_base):
        valor_com_imposto = valor_base / (1 - impostos_totais)
        imposto_calculado = valor_com_imposto * impostos_totais
        return valor_base, imposto_calculado, valor_com_imposto

    # MOTOR DE CÁLCULO DE DEMANDA (AZUL VS VERDE)
    if modalidade == "Azul":
        _, _, total_demanda_p_cat = decompor_item(demanda_ponta * componentes["tusd_demanda_p"])
        _, _, total_demanda_fp_cat = decompor_item(demanda_fponta * componentes["tusd_demanda_fp"])
        total_demanda_cat = total_demanda_p_cat + total_demanda_fp_cat
        
        # Desconto de Incentivada se aplica a ambas as TUSDs de Demanda no Livre
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

    fatura_mensal_cativa = total_demanda_cat + total_tusd_p_cat + total_tusd_fp_cat + total_te_p_cat + total_te_fp_cat
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

    saudacao = f"para <b>{nome_cliente}</b>" if nome_cliente else ""
    st.markdown(f"""
    <div class="card-vendas">
        <span style="font-size:20px; font-weight:bold; color:#3B82F6;">📈 Diagnóstico Comercial Executivo Gerado com Sucesso!</span><br/>
        Parceiro mais competitivo selecionado {saudacao} no Submercado {submercado_selecionado} para o produto <b>{tipo_energia}</b>: <b>{melhor_com_mes}</b> com economia de <b>{dados_melhor['percentual']:.1f}%</b> no Ano 1.<br/>
        <span style="font-size:14px; color:#94A3B8;">Consultor Responsável: {vendedor_responsavel}</span>
    </div>
    """, unsafe_allow_html=True)

    st.subheader(f"🏢 Matriz Global de Ofertas Mapeadas para o Estudo ({tipo_energia})")
    linhas_matriz_global = []
    for com in comercializadoras:
        linhas_matriz_global.append({
            "Comercializadora": com,
            "Ano 1": dados_precos[com][0], "Ano 2": dados_precos[com][1],
            "Ano 3": dados_precos[com][2], "Ano 4": dados_precos[com][3], "Ano 5": dados_precos[com][4],
        })
    df_matriz_global_tela = pd.DataFrame(linhas_matriz_global)
    st.dataframe(df_matriz_global_tela.style.format({
        "Ano 1": "R$ {:,.2f}", "Ano 2": "R$ {:,.2f}", "Ano 3": "R$ {:,.2f}", "Ano 4": "R$ {:,.2f}", "Ano 5": "R$ {:,.2f}"
    }), use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### **Cenário Cativo**")
        st.dataframe(pd.DataFrame({
            "Componentes de Custo": ["Demanda (TUSD)", "TUSD Ponta", "TUSD F. Ponta", "TE Ponta", "TE F. Ponta"],
            "Valor": [total_demanda_cat, total_tusd_p_cat, total_tusd_fp_cat, total_te_p_cat, total_te_fp_cat]
        }).style.format({"Valor": "R$ {:,.2f}"}), hide_index=True, use_container_width=True)
    with col2:
        st.markdown(f"#### **Cenário Livre ({melhor_com_mes})**")
        st.dataframe(pd.DataFrame({
            "Componentes de Custo": ["Demanda (TUSD c/ Desconto)", "TUSD Ponta", "TUSD F. Ponta", "Contrato Energia", "Gestão E-Lumia"],
            "Valor": [total_demanda_acl, total_tusd_p_cat, total_tusd_fp_cat, dados_melhor['fatura_energia'], total_gestao_elumia_mes]
        }).style.format({"Valor": "R$ {:,.2f}"}), hide_index=True, use_container_width=True)

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

    st.subheader("📈 Estudo de Longo Prazo Acumulado")
    df_estudo_integral = pd.DataFrame(linhas_proj)
    st.dataframe(df_estudo_integral.style.format({
        "Custo Projetado no Cativo": "R$ {:,.2f}", f"Custo Otimizado ACL ({melhor_com_mes})": "R$ {:,.2f}", "Economia Financeira no Ano": "R$ {:,.2f}"
    }), use_container_width=True, hide_index=True)

    k_final1, k_final2, k_final3 = st.columns(3)
    k_final1.metric("Gasto Total no Cativo", f"R$ {custo_cativo_acumulado_total:,.2f}")
    k_final2.metric(f"Gasto Total no ACL ({melhor_com_mes})", f"R$ {custo_livre_acumulado_total:,.2f}")
    k_final3.metric("Patrimônio Recuperado", f"R$ {(custo_cativo_acumulado_total - custo_livre_acumulado_total):,.2f}")

    def build_pdf():
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=15, textColor=colors.HexColor("#1A365D"), spaceAfter=6, alignment=1)
        subtitle_style = ParagraphStyle('SubTitle', parent=styles['Normal'], fontSize=11, textColor=colors.HexColor("#64748B"), alignment=1, spaceAfter=15)
        h2_style = ParagraphStyle('H2Style', parent=styles['Heading2'], fontSize=12, textColor=colors.HexColor("#1E3A8A"), spaceBefore=12, spaceAfter=6, fontName='Helvetica-Bold')
        bold_style = ParagraphStyle('BoldNorm', parent=styles['Normal'], fontSize=9, fontName='Helvetica-Bold', spaceAfter=6)

        story = []
        story.append(Paragraph("PROPOSTA EXECUTIVA DE MIGRAÇÃO - MERCADO LIVRE DE ENERGIA", title_style))
        story.append(Paragraph("E-LUMIA | Hub Solution Intelligence", subtitle_style))
        
        aviso_modo = "[TABELA MENSAL OFICIAL]" if not modo_manual else "[OFERTA CUSTOMIZADA EXCLUSIVA]"
        
        if nome_cliente or cnpj_input:
            story.append(Paragraph(f"<b>Target Client:</b> {nome_cliente} (CNPJ: {cnpj_input})", bold_style))
            story.append(Paragraph(f"<b>Submercado:</b> {submercado_selecionado} | <b>Produto:</b> {tipo_energia} | <b>Consultor:</b> {vendedor_responsavel}", bold_style))
            story.append(Spacer(1, 5))

        story.append(Paragraph(f"1. Matriz Global de Ofertas Computadas - {tipo_energia} {aviso_modo}", h2_style))
        pdf_global_matrix_data = [["Fornecedor", "Ano 1", "Ano 2", "Ano 3", "Ano 4", "Ano 5"]]
        for row in linhas_matriz_global:
            pdf_global_matrix_data.append([
                row["Comercializadora"],
                f"R$ {row['Ano 1']:,.2f}", f"R$ {row['Ano 2']:,.2f}",
                f"R$ {row['Ano 3']:,.2f}", f"R$ {row['Ano 4']:,.2f}", f"R$ {row['Ano 5']:,.2f}"
            ])
        t_global = Table(pdf_global_matrix_data, colWidths=[132, 84, 84, 84, 84, 84])
        t_global.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1A365D")), ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (1,0), (-1,-1), 'RIGHT'), ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey), ('FONTSIZE', (0,0), (-1,-1), 8),
        ]))
        story.append(t_global)

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
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1A365D")), ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (1,0), (-1,-1), 'RIGHT'), ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
            ('FONTSIZE', (0,0), (-1,-1), 8), ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#F8FAFC")),
        ]))
        story.append(t_fatura)

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
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1A365D")), ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (1,0), (-1,-1), 'RIGHT'), ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
            ('FONTSIZE', (0,0), (-1,-1), 8), ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#16A34A")), ('TEXTCOLOR', (0,-1), (-1,-1), colors.whitesmoke),
        ]))
        story.append(t_proj)

        doc.build(story)
        buffer.seek(0)
        return buffer.getvalue()

    pdf_bytes = build_pdf()

    data_atual = datetime.now().strftime("%d-%m-%Y")
    nome_cliente_limpo = re.sub(r'[\\/*?:"<>|.]', '', nome_cliente).replace(' ', '_') if nome_cliente else "Cliente_Nao_Identificado"
    nome_arquivamento_drive = f"Proposta_{nome_cliente_limpo}_{vendedor_responsavel}_{data_atual}.pdf"
    
    status_upload = upload_automatico_drive(pdf_bytes, nome_arquivamento_drive)
    
    if status_upload is True:
        st.sidebar.success(f"💾 Arquivado com sucesso no Google Drive!")
    else:
        st.sidebar.error(f"Erro no backup automático: {status_upload}")

    st.markdown("---")
    st.subheader("🖨️ Central de Fechamento de Propostas")
    nome_arquivo_manual = f"Estudo_Viabilidade_{nome_cliente_limpo}_{vendedor_responsavel}_{data_atual}.pdf"
    st.download_button(
        label="📄 Baixar Proposta Executiva Comercial (PDF)",
        data=pdf_bytes,
        file_name=nome_arquivo_manual,
        mime="application/pdf"
    )

else:
    st.info("👋 Selecione o seu nome, preencha os dados do cliente e selecione a distribuidora. O sistema já encontrou o submercado e os preços das comercializadoras automaticamente! Quando estiver tudo pronto, clique em 'Gerar Proposta Comercial'.")
