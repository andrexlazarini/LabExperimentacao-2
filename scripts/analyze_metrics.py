"""
analyze_metrics.py
-------------------
Analisa os dados do metrics_summary.csv respondendo às 4 questões de pesquisa:

  RQ01 - Popularidade (estrelas) × qualidade (CBO, DIT, LCOM)
  RQ02 - Maturidade   (idade_anos) × qualidade
  RQ03 - Atividade    (total_releases) × qualidade
  RQ04 - Tamanho      (loc_total) × qualidade

Gera:
  - Tabelas de medidas centrais por RQ (CSV)
  - Gráficos de dispersão com linha de tendência (PNG)
  - Resultados do teste de correlação de Spearman (CSV + console)
  - Heatmap de correlações geral

Saída em:  results/analysis/
"""

import csv
import os
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import seaborn as sns

ROOT = Path(__file__).resolve().parent.parent
SUMMARY_CSV = ROOT / "results" / "metrics_summary.csv"
OUT_DIR = ROOT / "results" / "analysis"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Paleta consistente
PALETTE = {
    "cbo":  "#2196F3",
    "dit":  "#4CAF50",
    "lcom": "#FF5722",
}

QUALITY_METRICS = [
    ("cbo_mediana",  "CBO (mediana)", PALETTE["cbo"]),
    ("dit_mediana",  "DIT (mediana)", PALETTE["dit"]),
    ("lcom_mediana", "LCOM (mediana)", PALETTE["lcom"]),
]

PROCESS_METRICS = [
    ("estrelas",        "Popularidade (estrelas)",   "RQ01"),
    ("idade_anos",      "Maturidade (anos)",          "RQ02"),
    ("total_releases",  "Atividade (releases)",       "RQ03"),
    ("loc_total",       "Tamanho (LOC total)",        "RQ04"),
]


# ──────────────────────────────────────────────
# Carregamento e limpeza
# ──────────────────────────────────────────────

def load_data() -> pd.DataFrame:
    df = pd.read_csv(SUMMARY_CSV, encoding="utf-8")

    numeric_cols = [
        "estrelas", "idade_anos", "total_releases",
        "cbo_mediana", "cbo_media", "cbo_desvio",
        "dit_mediana", "dit_media", "dit_desvio",
        "lcom_mediana", "lcom_media", "lcom_desvio",
        "loc_mediana", "loc_media", "loc_total",
        "comentarios_mediana", "comentarios_media", "comentarios_total",
        "total_classes",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Remover linhas com releases = -1 (falha na coleta)
    df = df[df["total_releases"] >= 0].copy()

    print(f"Dados carregados: {len(df)} repositórios")
    return df


# ──────────────────────────────────────────────
# Medidas centrais
# ──────────────────────────────────────────────

def central_measures(df: pd.DataFrame) -> pd.DataFrame:
    """Estatísticas descritivas gerais para todas as métricas numéricas."""
    cols = [
        "estrelas", "idade_anos", "total_releases",
        "cbo_mediana", "dit_mediana", "lcom_mediana",
        "loc_total", "total_classes",
    ]
    rows = []
    for col in cols:
        s = df[col].dropna()
        rows.append({
            "metrica": col,
            "n": len(s),
            "media": round(s.mean(), 4),
            "mediana": round(s.median(), 4),
            "desvio_padrao": round(s.std(), 4),
            "minimo": round(s.min(), 4),
            "maximo": round(s.max(), 4),
            "q25": round(s.quantile(0.25), 4),
            "q75": round(s.quantile(0.75), 4),
        })
    result = pd.DataFrame(rows)
    result.to_csv(OUT_DIR / "medidas_centrais.csv", index=False)
    return result


# ──────────────────────────────────────────────
# Correlação de Spearman
# ──────────────────────────────────────────────

def spearman_table(df: pd.DataFrame) -> pd.DataFrame:
    """Correlação de Spearman entre cada métrica de processo e cada métrica de qualidade."""
    rows = []
    for proc_col, proc_label, rq in PROCESS_METRICS:
        for qual_col, qual_label, _ in QUALITY_METRICS:
            sub = df[[proc_col, qual_col]].dropna()
            if len(sub) < 5:
                continue
            rho, pval = stats.spearmanr(sub[proc_col], sub[qual_col])
            rows.append({
                "RQ": rq,
                "processo": proc_label,
                "qualidade": qual_label,
                "spearman_rho": round(rho, 4),
                "p_value": round(pval, 6),
                "significativo": "sim" if pval < 0.05 else "não",
                "n": len(sub),
            })
    result = pd.DataFrame(rows)
    result.to_csv(OUT_DIR / "spearman_results.csv", index=False)
    return result


# ──────────────────────────────────────────────
# Gráficos de dispersão por RQ
# ──────────────────────────────────────────────

def scatter_rq(df: pd.DataFrame, proc_col: str, proc_label: str, rq: str):
    """Três sub-gráficos (CBO, DIT, LCOM) para uma questão de pesquisa."""
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    fig.suptitle(f"{rq} – {proc_label}", fontsize=14, fontweight="bold")

    for ax, (qual_col, qual_label, color) in zip(axes, QUALITY_METRICS):
        sub = df[[proc_col, qual_col]].dropna()
        x = sub[proc_col].values
        y = sub[qual_col].values

        # Remover outliers extremos para melhor visualização (manter 98%)
        x_p1, x_p99 = np.percentile(x, 1), np.percentile(x, 99)
        y_p1, y_p99 = np.percentile(y, 1), np.percentile(y, 99)
        mask = (x >= x_p1) & (x <= x_p99) & (y >= y_p1) & (y <= y_p99)
        x_plot, y_plot = x[mask], y[mask]

        ax.scatter(x_plot, y_plot, alpha=0.45, s=30, color=color, edgecolors="none")

        # Linha de tendência (regressão linear nos dados plotados)
        if len(x_plot) > 2:
            m, b, r, p, se = stats.linregress(x_plot, y_plot)
            x_line = np.linspace(x_plot.min(), x_plot.max(), 200)
            ax.plot(x_line, m * x_line + b, color="black", linewidth=1.5,
                    label=f"tendência (r={r:.2f})")
            ax.legend(fontsize=8)

        rho, pval = stats.spearmanr(x, y)
        sig = "*" if pval < 0.05 else ""
        ax.set_title(f"{qual_label}\nρ={rho:.3f}{sig}  p={pval:.4f}", fontsize=10)
        ax.set_xlabel(proc_label, fontsize=9)
        ax.set_ylabel(qual_label, fontsize=9)
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(OUT_DIR / f"{rq.lower()}_scatter.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Gráfico salvo: {rq.lower()}_scatter.png")


# ──────────────────────────────────────────────
# Heatmap de correlações
# ──────────────────────────────────────────────

def correlation_heatmap(df: pd.DataFrame):
    cols = [
        "estrelas", "idade_anos", "total_releases", "loc_total",
        "cbo_mediana", "dit_mediana", "lcom_mediana",
        "total_classes",
    ]
    labels = {
        "estrelas": "Estrelas", "idade_anos": "Idade (anos)",
        "total_releases": "Releases", "loc_total": "LOC total",
        "cbo_mediana": "CBO", "dit_mediana": "DIT",
        "lcom_mediana": "LCOM", "total_classes": "Nº Classes",
    }
    sub = df[cols].dropna()
    corr_matrix = sub.corr(method="spearman")
    corr_matrix.rename(columns=labels, index=labels, inplace=True)

    fig, ax = plt.subplots(figsize=(10, 8))
    mask = np.triu(np.ones_like(corr_matrix, dtype=bool))
    sns.heatmap(
        corr_matrix, mask=mask, annot=True, fmt=".2f",
        cmap="RdYlGn", center=0, vmin=-1, vmax=1,
        linewidths=0.5, ax=ax, annot_kws={"size": 10},
    )
    ax.set_title("Matriz de Correlação de Spearman\n(métricas de processo × qualidade)", fontsize=13)
    plt.tight_layout()
    fig.savefig(OUT_DIR / "heatmap_correlacoes.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  Heatmap salvo: heatmap_correlacoes.png")


# ──────────────────────────────────────────────
# Boxplots de qualidade por faixas de processo
# ──────────────────────────────────────────────

def boxplot_by_quartile(df: pd.DataFrame):
    """Boxplot das métricas de qualidade divididas em quartis de cada processo."""
    fig, axes = plt.subplots(4, 3, figsize=(18, 22))
    fig.suptitle("Qualidade por Quartis de Métricas de Processo", fontsize=14, fontweight="bold")

    quartile_labels = ["Q1 (baixo)", "Q2", "Q3", "Q4 (alto)"]

    for row_idx, (proc_col, proc_label, rq) in enumerate(PROCESS_METRICS):
        df[f"{proc_col}_q"] = pd.qcut(df[proc_col], 4, labels=quartile_labels)
        for col_idx, (qual_col, qual_label, color) in enumerate(QUALITY_METRICS):
            ax = axes[row_idx][col_idx]
            data_by_q = [
                df[df[f"{proc_col}_q"] == ql][qual_col].dropna().values
                for ql in quartile_labels
            ]
            bp = ax.boxplot(data_by_q, patch_artist=True, medianprops=dict(color="black", linewidth=2))
            for patch in bp["boxes"]:
                patch.set_facecolor(color)
                patch.set_alpha(0.6)
            ax.set_xticklabels(quartile_labels, rotation=15, fontsize=8)
            ax.set_title(f"{rq}: {qual_label}", fontsize=9, fontweight="bold")
            ax.set_xlabel(f"Quartis de {proc_label.split('(')[0].strip()}", fontsize=8)
            ax.set_ylabel(qual_label, fontsize=8)
            ax.grid(True, alpha=0.3, axis="y")

    plt.tight_layout()
    fig.savefig(OUT_DIR / "boxplots_quartis.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  Boxplots salvo: boxplots_quartis.png")


# ──────────────────────────────────────────────
# Distribuições individuais das métricas de qualidade
# ──────────────────────────────────────────────

def distribution_plots(df: pd.DataFrame):
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle("Distribuição das Métricas de Qualidade (todos os repositórios)", fontsize=13)

    for ax, (col, label, color) in zip(axes, QUALITY_METRICS):
        vals = df[col].dropna()
        # Limitar ao p99 para melhor visualização
        p99 = vals.quantile(0.99)
        vals_plot = vals[vals <= p99]
        ax.hist(vals_plot, bins=40, color=color, alpha=0.75, edgecolor="white")
        ax.axvline(vals.median(), color="black", linestyle="--", linewidth=1.5,
                   label=f"mediana={vals.median():.2f}")
        ax.axvline(vals.mean(), color="red", linestyle=":", linewidth=1.5,
                   label=f"média={vals.mean():.2f}")
        ax.set_title(label, fontsize=11)
        ax.set_xlabel("Valor")
        ax.set_ylabel("Frequência")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(OUT_DIR / "distribuicoes_qualidade.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  Distribuições salvo: distribuicoes_qualidade.png")


# ──────────────────────────────────────────────
# Sumário por RQ (medidas centrais segmentadas)
# ──────────────────────────────────────────────

def rq_summary_tables(df: pd.DataFrame):
    """Gera uma tabela de medidas centrais para cada RQ."""
    for proc_col, proc_label, rq in PROCESS_METRICS:
        df[f"{proc_col}_q"] = pd.qcut(df[proc_col], 4,
                                       labels=["Q1 (baixo)", "Q2", "Q3", "Q4 (alto)"])
        rows = []
        for ql in ["Q1 (baixo)", "Q2", "Q3", "Q4 (alto)"]:
            sub = df[df[f"{proc_col}_q"] == ql]
            for qcol, qlabel, _ in QUALITY_METRICS:
                s = sub[qcol].dropna()
                rows.append({
                    "quartil": ql,
                    "metrica_qualidade": qlabel,
                    "n": len(s),
                    "media": round(s.mean(), 4),
                    "mediana": round(s.median(), 4),
                    "desvio": round(s.std(), 4),
                })
        pd.DataFrame(rows).to_csv(OUT_DIR / f"{rq.lower()}_summary.csv", index=False)
    print("  Tabelas RQ salvas.")


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Análise de Qualidade de Repositórios Java")
    print("=" * 60)

    df = load_data()

    print("\n[1/6] Calculando medidas centrais...")
    cm = central_measures(df)
    print(cm.to_string(index=False))

    print("\n[2/6] Calculando correlações de Spearman...")
    sp = spearman_table(df)
    print(sp.to_string(index=False))

    print("\n[3/6] Gerando gráficos de dispersão por RQ...")
    for proc_col, proc_label, rq in PROCESS_METRICS:
        scatter_rq(df, proc_col, proc_label, rq)

    print("\n[4/6] Gerando heatmap de correlações...")
    correlation_heatmap(df)

    print("\n[5/6] Gerando boxplots por quartis...")
    boxplot_by_quartile(df)

    print("\n[6/6] Gerando distribuições e tabelas de RQ...")
    distribution_plots(df)
    rq_summary_tables(df)

    print(f"\nTodos os artefatos salvos em: {OUT_DIR}")
    print("\n--- RESUMO CORRELAÇÕES DE SPEARMAN ---")
    for _, row in sp.iterrows():
        sig_mark = " ***" if row["p_value"] < 0.001 else (" **" if row["p_value"] < 0.01 else (" *" if row["p_value"] < 0.05 else ""))
        print(f"  {row['RQ']} | {row['processo']:30} x {row['qualidade']:15} | "
              f"rho={row['spearman_rho']:+.3f}  p={row['p_value']:.4f}{sig_mark}")


if __name__ == "__main__":
    main()
