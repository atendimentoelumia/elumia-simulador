import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import requests
import re
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# Configuração da página - E-Lumia Executive BI
st.set_page_config(page_title="E-Lumia | Hub Solution Intelligence", layout="wide", initial_sidebar_state="expanded")

# CSS Ajustado para Dark Mode
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

# --- INTEGRAÇÃO: LEITURA DO CSV LOCAL ---
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
                mask = (
                    (df[col_sigla] == concessionaria) & 
                    (df[col_sub] == subgrupo) & 
                    (df[col_mod] == modalidade)
                )
                df_filtered = df[mask].copy()

                if not df_filtered.empty:
                    if col_te:
                        if df_filtered[col_te].dtype == 'object':
                            df_filtered[col_te] = pd.to_numeric(df_filtered[col_te].astype(str).str.replace(',', '.'), errors='coerce').fillna(0) * 1000
                        else:
                            df_filtered[col_te] = df_filtered[col_te] * 1000
                    
                    if col_tusd:
                        if df_filtered[col_tusd].dtype == 'object':
                            df_filtered[col_tusd] = pd.to_numeric(df_filtered[col_tusd].astype(str).str.replace(',', '.'), errors='coerce').fillna(0) * 1000
                        else:
                            df_filtered[col_tusd] = df_filtered[col_tusd] * 1000

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
            st.sidebar.warning(f"Aviso: Erro ao processar dados internos do CSV ({e}). Usando médias de mercado.")

    return {
        "tusd_demanda": tusd_demanda if not np.isnan(tusd_demanda) else 22.0,
        "tusd_energia_p": tusd_energia_p if not np.isnan(tusd_energia_p) else 250.0,
        "tusd_energia_fp": tusd_energia_fp if not np.isnan(tusd_energia_fp) else 80.0,
        "te_p": te_p if not np.isnan(te_p) else 550.0,
        "te_fp": te_fp if not np.isnan(te_fp) else 320.0
    }

# --- PARÂMETROS COMERCIAIS ---
st.sidebar.header("🎯 Qualificação do Cliente")

# INTEGRAÇÃO DE API CNPJ
if "nome_cliente_auto" not in st.session_state:
    st.session_state.nome_cliente_auto = ""

cnpj_input = st.sidebar.text_input("CNPJ (Aperte Enter para buscar)", placeholder="00.000.000/0000-00")

if cnpj_input:
    # Limpa o texto deixando apenas os números
    cnpj_limpo = re.sub(r'[^0-9]', '', cnpj_input)
    
    if len(cnpj_limpo) == 14:
        with st.sidebar.spinner("Consultando Receita Federal..."):
            try:
                # Consulta na BrasilAPI (Gratuita e sem limites estritos)
                response = requests.get(f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}", timeout=10)
                if response.status_code == 200:
                    dados = response.json()
                    st.session_state.nome_cliente_auto = dados.get('razao_social', '')
                    st.sidebar.success("CNPJ Validado e Ativo!")
                else:
                    st.sidebar.error("CNPJ não encontrado na base.")
            except Exception:
                st.sidebar.warning("Aviso: Instabilidade na validação online.")
    elif len(cnpj_limpo) > 0:
        st.sidebar.warning("Um CNPJ deve conter exatamente 14 números.")

nome_cliente = st.sidebar.text_input("Nome / Razão Social", value=st.session_state.nome_cliente_auto)
st.sidebar.markdown("---")

list_concessionarias = fetch_aneel_companies()
concessionaria = st.sidebar.selectbox("Distribuidora Atual", list_concessionarias)

dados_fiscais = MAPA_IMPOSTOS.get(concessionaria, {"UF": "SP", "ICMS": 0.18, "PIS_COFINS": 0.0925})
impostos_totais = dados_fiscais["ICMS"] + dados_fiscais["PIS_COFINS"]

subgrupo = st.sidebar.selectbox("Subgrupo Tarifário", ["A4", "A3"])
modalidade = st.sidebar.selectbox("Modalidade na Distribuidora", ["Verde", "Azul"])
tempo_contrato = st.sidebar.slider("Horizonte do Planejamento (Meses)", 12, 60, 36, step=12)
tipo_energia = st.sidebar.selectbox("Produto de Energia Sugerido", ["Convencional", "Incentivada 50%", "Incentivada 100%"])

fator_desconto_demanda = 1.0 if tipo_energia == "Convencional" else (0.5 if tipo_energia == "Incentivada 50%" else 0.0)

st.sidebar.subheader("📊 Métricas de Consumo (Fatura)")
demanda_contratada = st.sidebar.number_input("Demanda Contratada (kW)", value=500.0)
consumo_kwh_fp = st.sidebar.number_input("Consumo Fora Ponta (kWh/mês)", value=120000.0, step=5000.0)
consumo_kwh_p = st.sidebar.number_input("Consumo Ponta (kWh/mês)", value=15000.0, step=1000.0)

fee_elumia_mwh = st.sidebar.number_input("Gestão Executiva E-Lumia (R$/MWh)", value=6.00, format="%.2f")

# Conversões internas
consumo_fp = consumo_kwh_fp / 1000
consumo_p = consumo_kwh_p / 1000
consumo_total_mes_kwh = consumo_kwh_fp + consumo_kwh_p
consumo_total_ano_mwh = (consumo_total_mes_kwh / 1000) * 12
fee_elumia = fee_elumia_mwh

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

# --- ENGINE DE CÁLCULO MENSAL ESPELHADO ---
def decompor_item(valor_base):
    valor_com_imposto = valor_base / (1 - impostos_totais)
    imposto_calculado = valor_com_imposto * impostos_totais
    return valor_base, imposto_calculado, valor_com_imposto

# 1. Detalhamento Fatura Atual (Cativo)
_, _, total_demanda_cat = decompor_item(demanda_contratada * componentes["tusd_demanda"])
_, _, total_tusd_p_cat = decompor_item(consumo_p * componentes["tusd_energia_p"])
_, _, total_tusd_fp_cat = decompor_item(consumo_fp * componentes["tusd_energia_fp"])
_, _, total_te_p_cat = decompor_item(consumo_p * componentes["te_p"])
_, _, total_te_fp_cat = decompor_item(consumo_fp * componentes["te_fp"])

fatura_mensal_cativa = total_demanda_cat + total_tusd_p_cat + total_tusd_fp_cat + total_te_p_cat + total_te_fp_cat

# 2. Detalhamento da Fatura que permanece na Concessionária estando no ACL
_, _, total_demanda_acl = decompor_item(demanda_contratada * componentes["tusd_demanda"] * fator_desconto_demanda)
fatura_residual_concessionaria_acl = total_demanda_acl + total_tusd_p_cat + total_tusd_fp_cat

# Fee E-Lumia mensal com imposto (MWh * Valor de Gestão)
_, _, total_gestao_elumia_mes = decompor_item((consumo_total_mes_kwh / 1000) * fee_elumia)

# --- COMPARAÇÃO MULTIFORNECEALIDORAS (ANO 1) ---
resultados_comercializadoras_mes = {}
for com in comercializadoras:
    preco_ano1 = dados_precos[com][0]
    _, _, total_energia_comercializadora_mes = decompor_item((consumo_total_mes_kwh / 1000) * preco_ano1)
    
    total_acl_com_fornecedor = fatura_residual_concessionaria_acl + total_energia_comercializadora_mes + total_gestao_elumia_mes
    economia_mes_fornecedor = fatura_mensal_cativa - total_acl_com_fornecedor
    percentual_economia_fornecedor = (economia_mes_fornecedor / fatura_mensal_cativa) * 100
    
    resultados_comercializadoras_mes[com] = {
        "fatura_energia": total_energia_comercializadora_mes,
        "custo_total_acl": total_acl_com_fornecedor,
        "economia_reais": economia_mes_fornecedor,
        "percentual": percentual_economia_fornecedor
    }

# Seleciona o melhor para o destaque principal da tela
melhor_com_mes = min(resultados_comercializadoras_mes, key=lambda k: resultados_comercializadoras_mes[k]["custo_total_acl"])
dados_melhor = resultados_comercializadoras_mes[melhor_com_mes]

# --- APRESENTAÇÃO DOS DADOS NA TELA ---
st.title("⚡ E-Lumia | Hub Solution Intelligence")
st.markdown("## Estudo Comparativo de Faturamento: Cativo vs. Mercado Livre")

# Saudação personalizada se o cliente estiver preenchido
saudacao_cliente = f"para <b>{nome_cliente}</b>" if nome_cliente else "para a sua empresa"

st.markdown(f"""
<div class="card-vendas">
    <span style="font-size:20px; font-weight:bold; color:#3B82F6;">📈 Diagnóstico Comercial Executivo</span><br/>
    Identificamos que o parceiro mais competitivo no 1º ano {saudacao_cliente} é a <b>{melhor_com_mes}</b>. 
    A migração garante uma redução real de <b>{dados_melhor['percentual']:.1f}%</b> nas despesas operacionais com energia elétrica.
</div>
""", unsafe_allow_html=True)

# SEÇÃO 1: COMPARATIVO LADO A LADO DO DESEMBOLSO MENSAL
st.subheader("📋 Espelhamento e Engenharia das Faturas (Base Mensal Atual)")
col_cat, col_acl = st.columns(2)

with col_cat:
    st.markdown("#### **Cenário Atual: Mercado Cativo**")
    df_linhas_cat = pd.DataFrame({
        "Linha de Custo / Conta Distribuidora": [
            "TUSD Demanda Contratada",
            "TUSD Consumo Ponta",
            "TUSD Consumo Fora Ponta",
            "TE Tarifa de Energia Ponta",
            "TE Tarifa de Energia Fora Ponta"
        ],
        "Destino do Pagamento": ["Concessionária Local", "Concessionária Local", "Concessionária Local", "Concessionária Local", "Concessionária Local"],
        "Valor com Impostos": [total_demanda_cat, total_tusd_p_cat, total_tusd_fp_cat, total_te_p_cat, total_te_fp_cat]
    })
    st.dataframe(df_linhas_cat.style.format({"Valor com Impostos": "R$ {:,.2f}"}), use_container_width=True, hide_index=True)
    st.metric("Desembolso Mensal Total Cativo", f"R$ {fatura_mensal_cativa:,.2f}")

with col_acl:
    st.markdown(f"#### **Cenário Proposto: Mercado Livre ({melhor_com_mes})**")
    df_linhas_acl = pd.DataFrame({
        "Linha de Custo / Novas Faturas": [
            f"TUSD Demanda Contratada ({tipo_energia})",
            "TUSD Consumo Ponta",
            "TUSD Consumo Fora Ponta",
            f"Contrato de Fornecimento de Energia",
            "Fee de Gestão Inteligente"
        ],
        "Destino do Pagamento": ["Concessionária Local", "Concessionária Local", "Concessionária Local", melhor_com_mes, "E-Lumia"],
        "Valor com Impostos": [total_demanda_acl, total_tusd_p_cat, total_tusd_fp_cat, dados_melhor['fatura_energia'], total_gestao_elumia_mes]
    })
    st.dataframe(df_linhas_acl.style.format({"Valor com Impostos": "R$ {:,.2f}"}), use_container_width=True, hide_index=True)
    st.metric("Desembolso Mensal Total ACL", f"R$ {dados_melhor['custo_total_acl']:,.2f}", 
              delta=f"Economia Mensal Correta: R$ {dados_melhor['economia_reais']:,.2f} (-{dados_melhor['percentual']:.1f}%)", delta_color="inverse")

# SEÇÃO 2: GRÁFICOS GERENCIAIS DE PESO E ELEMENTOS
st.markdown("### 📊 Decomposição Visual e Peso de Elementos na Fatura")
col_g1, col_g2 = st.columns(2)

with col_g1:
    st.markdown("**Distribuição de Peso da Fatura Atual (Cativo)**")
    base_demanda_pura, imp_dem, _ = decompor_item(demanda_contratada * componentes["tusd_demanda"])
    base_t_p, imp_tp, _ = decompor_item(consumo_p * componentes["tusd_energia_p"])
    base_t_fp, imp_tfp, _ = decompor_item(consumo_fp * componentes["tusd_energia_fp"])
    base_te_p, imp_tep, _ = decompor_item(consumo_p * componentes["te_p"])
    base_te_fp, imp_tefp, _ = decompor_item(consumo_fp * componentes["te_fp"])
    
    df_pizza_cat = pd.DataFrame({
        "Componente": ["TUSD (Fio/Infraestrutura)", "TE (Energia Consumida)", "Impostos (ICMS + PIS/COFINS)"],
        "Valor": [
            base_demanda_pura + base_t_p + base_t_fp,
            base_te_p + base_te_fp,
            imp_dem + imp_tp + imp_tfp + imp_tep + imp_tefp
        ]
    })
    fig_cat = px.pie(df_pizza_cat, values="Valor", names="Componente", hole=0.4, color_discrete_sequence=["#3B82F6", "#38BDF8", "#F87171"])
    fig_cat.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=260)
    st.plotly_chart(fig_cat, use_container_width=True)

with col_g2:
    st.markdown("**Comportamento Financeiro no Mercado Livre (Para onde vai o pagamento?)**")
    df_pizza_acl = pd.DataFrame({
        "Destinatário": ["Faturamento Concessionária (TUSD)", "Faturamento Comercializadora (Energia)", "Faturamento Gestão (E-Lumia)"],
        "Valor": [fatura_residual_concessionaria_acl, dados_melhor['fatura_energia'], total_gestao_elumia_mes]
    })
    fig_acl = px.pie(df_pizza_acl, values="Valor", names="Destinatário", hole=0.4, color_discrete_sequence=["#94A3B8", "#4ADE80", "#FBBF24"])
    fig_acl.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=260)
    st.plotly_chart(fig_acl, use_container_width=True)

# SEÇÃO 3: COMPARATIVO DAS COMERCIALIZADORAS (MATRIZ DE CONVERSÃO)
st.subheader("🏢 Matriz Comparativa de Fornecedores (Ano 1)")
st.markdown("Veja o desempenho financeiro de cada comercializadora mapeada pela inteligência de mercado da E-Lumia:")

linhas_comparativas_com = []
for com in comercializadoras:
    res = resultados_comercializadoras_mes[com]
    linhas_comparativas_com.append({
        "Parceiro Comercializador": com,
        "Preço Ofertado (R$/MWh)": dados_precos[com][0],
        "Fatura da Distribuidora (R$)": fatura_residual_concessionaria_acl,
        "Fatura da Comercializadora (R$)": res["fatura_energia"],
        "Fee E-Lumia (R$)": total_gestao_elumia_mes,
        "Custo Mensal Total no ACL (R$)": res["custo_total_acl"],
        "Economia Mensal Gerada (R$)": res["economia_reais"],
        "Eficiência de Redução (%)": f"{res['percentual']:.2f}%"
    })

df_matriz_comercializadoras = pd.DataFrame(linhas_comparativas_com)
st.dataframe(df_matriz_comercializadoras.style.format({
    "Preço Ofertado (R$/MWh)": "R$ {:,.2f}",
    "Fatura da Distribuidora (R$)": "R$ {:,.2f}",
    "Fatura da Comercializadora (R$)": "R$ {:,.2f}",
    "Fee E-Lumia (R$)": "R$ {:,.2f}",
    "Custo Mensal Total no ACL (R$)": "R$ {:,.2f}",
    "Economia Mensal Gerada (R$)": "R$ {:,.2f}"
}), use_container_width=True, hide_index=True)

# --- ENGINE DE CONSTRUÇÃO DO df_projecao ---
linhas_proj = []
anos_reais = int(tempo_contrato / 12)

for ano_idx in range(anos_reais):
    fator_distribuidora = (1 + 0.08) ** ano_idx
    fator_energia_livre = (1 + 0.06) ** ano_idx 
    
    custo_cativo_ano = (fatura_mensal_cativa * 12) * fator_distribuidora
    row = {"Ano": ano_idx + 1, "Mercado Cativo": custo_cativo_ano}
    
    for com in comercializadoras:
        preco_inputado = dados_precos[com][ano_idx]
        preco_com_inflacao = preco_inputado * fator_energia_livre
        
        _, _, fatura_energia_ano = decompor_item((consumo_total_ano_mwh) * preco_com_inflacao)
        fatura_resid_ano = (fatura_residual_concessionaria_acl * 12) * fator_distribuidora
        fee_ano = (total_gestao_elumia_mes * 12) * fator_energia_livre
        
        row[com] = fatura_resid_ano + fatura_energia_ano + fee_ano
        
    linhas_proj.append(row)

df_projecao = pd.DataFrame(linhas_proj)
# -------------------------------------------

# SEÇÃO 4: ESTUDO DE LONGO PRAZO ACUMULADO ACORDADO EM CONTRATO
st.subheader(f"📈 Estudo de Viabilidade Integral do Contrato ({tempo_contrato} Meses)")

linhas_projecao_exibicao = []
custo_cativo_acumulado_total = 0
custo_livre_acumulado_total = 0

for idx in range(anos_reais):
    ano_num = idx + 1
    row_proj = df_projecao.iloc[idx]
    
    custo_cativo_ano = row_proj["Mercado Cativo"]
    custo_acl_ano = row_proj[melhor_com_mes]
    econ_ano = custo_cativo_ano - custo_acl_ano
    pct_econ_ano = (econ_ano / custo_cativo_ano) * 100
    
    custo_cativo_acumulado_total += custo_cativo_ano
    custo_livre_acumulado_total += custo_acl_ano
    
    linhas_projecao_exibicao.append({
        "Período": f"Ano {ano_num}",
        "Custo Projetado no Cativo": custo_cativo_ano,
        f"Custo Otimizado ACL ({melhor_com_mes})": custo_acl_ano,
        "Economia Financeira no Ano": econ_ano,
        "Margem de Redução Ano": f"{pct_econ_ano:.2f}%"
    })

df_estudo_integral = pd.DataFrame(linhas_projecao_exibicao)
st.dataframe(df_estudo_integral.style.format({
    "Custo Projetado no Cativo": "R$ {:,.2f}",
    f"Custo Otimizado ACL ({melhor_com_mes})": "R$ {:,.2f}",
    "Economia Financeira no Ano": "R$ {:,.2f}"
}), use_container_width=True, hide_index=True)

# KPIs de encerramento
st.markdown("#### **Resultado Líquido do Investimento no Horizonte Contratual**")
k_final1, k_final2, k_final3 = st.columns(3)
k_final1.metric("Gasto Total Acumulado no Cativo", f"R$ {custo_cativo_acumulado_total:,.2f}")
k_final2.metric(f"Gasto Total Acumulado no ACL ({melhor_com_mes})", f"R$ {custo_livre_acumulado_total:,.2f}")
k_final3.metric("Patrimônio Líquido Recuperado", f"R$ {(custo_cativo_acumulado_total - custo_livre_acumulado_total):,.2f}", 
                delta=f"{dados_melhor['percentual']:.1f}% de Ganho Médio")

# --- EXPORTAÇÃO COMPLETA PARA PDF (VERSÃO VENDAS EXECUTIVA) ---
def build_pdf():
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=15, textColor=colors.HexColor("#1A365D"), spaceAfter=6, alignment=1)
    subtitle_style = ParagraphStyle('SubTitle', parent=styles['Normal'], fontSize=11, textColor=colors.HexColor("#64748B"), alignment=1, spaceAfter=20)
    h2_style = ParagraphStyle('H2Style', parent=styles['Heading2'], fontSize=12, textColor=colors.HexColor("#1E3A8A"), spaceBefore=15, spaceAfter=8, fontName='Helvetica-Bold')
    normal_style = ParagraphStyle('Norm', parent=styles['Normal'], fontSize=10, spaceAfter=10)
    bold_style = ParagraphStyle('BoldNorm', parent=styles['Normal'], fontSize=10, fontName='Helvetica-Bold', spaceAfter=10)

    story = []
    
    # CABEÇALHO
    story.append(Paragraph("PROPOSTA EXECUTIVA DE MIGRAÇÃO - MERCADO LIVRE DE ENERGIA", title_style))
    story.append(Paragraph("E-LUMIA | Hub Solution Intelligence", subtitle_style))
    
    # Dados do Cliente no PDF
    if nome_cliente or cnpj_input:
        story.append(Paragraph(f"<b>Preparado exclusivamente para:</b> {nome_cliente} (CNPJ: {cnpj_input})", bold_style))
        story.append(Spacer(1, 10))

    story.append(Paragraph(f"Com base no mapeamento do seu perfil de consumo na <b>{concessionaria}</b>, desenvolvemos este estudo estratégico para a otimização de suas despesas operacionais através do Mercado Livre de Energia.", normal_style))

    # 1. RANKING DE COMERCIALIZADORAS
    story.append(Paragraph("1. Ranking de Competitividade de Fornecedores", h2_style))
    story.append(Paragraph("Nossa inteligência de mercado avaliou as principais comercializadoras do país. Abaixo, o ranking das melhores ofertas para o 1º ano do seu contrato, ordenadas pela economia financeira gerada:", normal_style))
    
    ranking_data = [["Posição", "Comercializadora", "Preço Ofertado", "Economia (Mês)", "Redução"]]
    sorted_coms = sorted(resultados_comercializadoras_mes.items(), key=lambda x: x[1]['custo_total_acl'])
    
    for i, (com, res) in enumerate(sorted_coms):
        preco_mwh = dados_precos[com][0]
        ranking_data.append([
            f"{i+1}º Lugar", com, f"R$ {preco_mwh:,.2f} /MWh", f"R$ {res['economia_reais']:,.2f}", f"{res['percentual']:.2f}%"
        ])

    t_ranking = Table(ranking_data, colWidths=[70, 150, 110, 110, 70])
    t_ranking.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1A365D")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('BACKGROUND', (0,1), (-1,1), colors.HexColor("#EFF6FF")), 
        ('FONTNAME', (0,1), (-1,1), 'Helvetica-Bold'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
    ]))
    story.append(t_ranking)
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"💡 <b>Decisão Recomendada:</b> A <b>{melhor_com_mes}</b> apresentou a melhor performance, garantindo <b>{dados_melhor['percentual']:.1f}%</b> de redução imediata nas faturas.", bold_style))

    # 2. COMPARATIVO FINANCEIRO MENSAL
    story.append(Paragraph("2. Engenharia Financeira Mensal (Visão Atual vs. Proposta)", h2_style))
    pdf_fatura_data = [
        ["Composição dos Custos", "Cenário Atual (Cativo)", f"Novo Cenário Livre ({melhor_com_mes})"],
        ["Faturamento Concessionária", f"R$ {fatura_mensal_cativa:,.2f}", f"R$ {fatura_residual_concessionaria_acl:,.2f}"],
        ["Faturamento Comercializadora", "-", f"R$ {dados_melhor['fatura_energia']:,.2f}"],
        ["Gestão Executiva E-Lumia", "-", f"R$ {total_gestao_elumia_mes:,.2f}"],
        ["Desembolso Total Estimado", f"R$ {fatura_mensal_cativa:,.2f}", f"R$ {dados_melhor['custo_total_acl']:,.2f}"]
    ]
    t_fatura = Table(pdf_fatura_data, colWidths=[200, 150, 160])
    t_fatura.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1A365D")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
        ('ALIGN', (0,0), (0,0), 'LEFT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#F8FAFC")), 
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
    ]))
    story.append(t_fatura)

    # 3. PROJEÇÃO DE LONGO PRAZO
    story.append(Paragraph(f"3. Estudo de Viabilidade e Blindagem ({tempo_contrato} Meses)", h2_style))
    story.append(Paragraph("A simulação abaixo considera um reajuste de 8% a.a. projetado no Mercado Cativo e na tarifa da Distribuidora (Fio), e um reajuste de 6% a.a. aplicado sobre o preço de Energia e Gestão no Mercado Livre:", normal_style))
    
    proj_data = [["Período", "Projeção Cativo (R$)", f"Projeção ACL (R$)", "Economia Financeira"]]
    for row in linhas_projecao_exibicao:
        proj_data.append([
            row["Período"],
            f"R$ {row['Custo Projetado no Cativo']:,.2f}",
            f"R$ {row[f'Custo Otimizado ACL ({melhor_com_mes})']:,.2f}",
            f"R$ {row['Economia Financeira no Ano']:,.2f}"
        ])

    # Linha final com os Resultados Totais Acumulados
    proj_data.append([
        "RESULTADO LÍQUIDO ACUMULADO",
        f"R$ {custo_cativo_acumulado_total:,.2f}",
        f"R$ {custo_livre_acumulado_total:,.2f}",
        f"R$ {(custo_cativo_acumulado_total - custo_livre_acumulado_total):,.2f}"
    ])

    t_proj = Table(proj_data, colWidths=[140, 110, 110, 130])
    t_proj.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1A365D")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
        ('ALIGN', (0,0), (0,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#16A34A")), 
        ('TEXTCOLOR', (0,-1), (-1,-1), colors.whitesmoke),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
    ]))
    story.append(t_proj)

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

st.subheader("🖨️ Central de Fechamento de Propostas")
pdf_data = build_pdf()

# Nome do arquivo customizado para o cliente
nome_arquivo = f"Estudo_Viabilidade_{nome_cliente.replace(' ', '_')}.pdf" if nome_cliente else "Estudo_Viabilidade_ELumia.pdf"

st.download_button(
    label="📄 Baixar Proposta Executiva Comercial (PDF)",
    data=pdf_data,
    file_name=nome_arquivo,
    mime="application/pdf"
)
