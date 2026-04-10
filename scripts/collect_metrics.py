"""
collect_metrics.py
-------------------
Clona cada repositório do repos.csv, roda o CK e salva as métricas
em results/metrics_summary.csv.

Características:
  - Retoma de onde parou (pula repos já processados no CSV)
  - Usa diretório temporário para não acumular disco
  - Timeout configurável por etapa
  - Log de erros separado (results/errors.log)

Uso:
  python collect_metrics.py --token ghp_XXX
  python collect_metrics.py --token ghp_XXX --limit 50   # processa só 50
  python collect_metrics.py --token ghp_XXX --start 101  # começa do repo 101
"""

import argparse
import csv
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPOS_CSV   = ROOT / "data"    / "repos.csv"
RESULTS_DIR = ROOT / "results"
SUMMARY_CSV = RESULTS_DIR / "metrics_summary.csv"
ERROR_LOG   = RESULTS_DIR / "errors.log"
CK_JAR      = ROOT / "ck.jar"

CK_JAR_URL = (
    "https://github.com/mauricioaniche/ck/releases/download/v0.7.1/"
    "ck-0.7.1-SNAPSHOT-jar-with-dependencies.jar"
)

SUMMARY_FIELDS = [
    "posicao", "nome_completo", "estrelas", "idade_anos", "total_releases",
    "cbo_mediana", "cbo_media", "cbo_desvio",
    "dit_mediana", "dit_media", "dit_desvio",
    "lcom_mediana", "lcom_media", "lcom_desvio",
    "loc_mediana", "loc_media", "loc_total",
    "comentarios_mediana", "comentarios_media", "comentarios_total",
    "total_classes",
]


# ── Utilitários ─────────────────────────────────────────────

def ensure_ck_jar():
    if CK_JAR.exists():
        return
    print(f"Baixando CK jar...")
    urllib.request.urlretrieve(CK_JAR_URL, CK_JAR)
    print("  Download concluído.")


def already_processed() -> set:
    """Retorna conjunto de nome_completo já presentes no CSV de saída."""
    if not SUMMARY_CSV.exists():
        return set()
    with open(SUMMARY_CSV, newline="", encoding="utf-8") as f:
        return {row["nome_completo"] for row in csv.DictReader(f)}


def log_error(msg: str):
    with open(ERROR_LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {msg}\n")


# ── GitHub: total de releases ────────────────────────────────

def count_releases(full_name: str, token: str | None) -> int:
    import json, re
    url = f"https://api.github.com/repos/{full_name}/releases?per_page=1"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            link = resp.headers.get("Link", "")
            if 'rel="last"' in link:
                m = re.search(r'page=(\d+)>; rel="last"', link)
                if m:
                    return int(m.group(1))
            return len(json.loads(resp.read()))
    except Exception as e:
        log_error(f"{full_name} | releases | {e}")
        return -1


# ── Git clone ────────────────────────────────────────────────

def clone_repo(full_name: str, dest: Path, timeout: int = 300):
    url = f"https://github.com/{full_name}.git"
    subprocess.run(
        ["git", "clone", "--depth", "1", "--quiet", url, str(dest)],
        check=True, timeout=timeout,
    )


# ── CK ───────────────────────────────────────────────────────

def run_ck(repo_dir: Path, output_dir: Path, timeout: int = 600) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["java", "-jar", str(CK_JAR),
         str(repo_dir), "false", "0", "false",
         str(output_dir) + os.sep],
        check=True, timeout=timeout, capture_output=True,
    )
    return output_dir / "class.csv"


# ── Sumarização do class.csv ─────────────────────────────────

def summarise(class_csv: Path) -> dict:
    cbo, dit, lcom, loc, comments = [], [], [], [], []

    with open(class_csv, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            try:
                cbo.append(float(row["cbo"]))
                dit.append(float(row["dit"]))
                lcom.append(float(row.get("lcom", row.get("lcom*", 0))))
                loc.append(float(row["loc"]))
                val = float(row.get("returnQty", 0))
                for k in ("comments", "commentLines", "comment"):
                    if k in row:
                        val = float(row[k])
                        break
                comments.append(val)
            except (ValueError, KeyError):
                continue

    def st(vals):
        if not vals:
            return 0.0, 0.0, 0.0
        med  = round(statistics.median(vals), 4)
        mean = round(statistics.mean(vals), 4)
        std  = round(statistics.stdev(vals) if len(vals) > 1 else 0.0, 4)
        return med, mean, std

    cm, ca, cs = st(cbo)
    dm, da, ds = st(dit)
    lm, la, ls = st(lcom)
    om, oa, _  = st(loc)
    km, ka, _  = st(comments)

    return {
        "cbo_mediana": cm, "cbo_media": ca, "cbo_desvio": cs,
        "dit_mediana": dm, "dit_media": da, "dit_desvio": ds,
        "lcom_mediana": lm, "lcom_media": la, "lcom_desvio": ls,
        "loc_mediana": om, "loc_media": oa, "loc_total": round(sum(loc), 0),
        "comentarios_mediana": km, "comentarios_media": ka,
        "comentarios_total": round(sum(comments), 0),
        "total_classes": len(cbo),
    }


# ── Main ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token",  default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--limit",  type=int, default=None,
                        help="Número máximo de repositórios a processar")
    parser.add_argument("--start",  type=int, default=1,
                        help="Posição inicial (posicao no CSV)")
    args = parser.parse_args()

    if not args.token:
        print("AVISO: sem token GitHub — contagem de releases pode falhar.")

    ensure_ck_jar()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Carrega lista de repos
    if not REPOS_CSV.exists():
        print(f"ERRO: {REPOS_CSV} não encontrado.", file=sys.stderr)
        sys.exit(1)
    with open(REPOS_CSV, newline="", encoding="utf-8") as f:
        all_repos = list(csv.DictReader(f))

    # Filtra intervalo solicitado
    repos = [r for r in all_repos if int(r["posicao"]) >= args.start]
    if args.limit:
        repos = repos[:args.limit]

    # Descobre quais já foram processados
    done = already_processed()
    pending = [r for r in repos if r["nome_completo"] not in done]

    print(f"Total no CSV         : {len(all_repos)}")
    print(f"Já processados       : {len(done)}")
    print(f"A processar agora    : {len(pending)}")
    print(f"Log de erros         : {ERROR_LOG}")
    print()

    # Abre CSV de saída em modo append
    write_header = not SUMMARY_CSV.exists()
    out_file = open(SUMMARY_CSV, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(out_file, fieldnames=SUMMARY_FIELDS)
    if write_header:
        writer.writeheader()

    t_start = time.time()
    ok = 0

    for idx, repo_info in enumerate(pending, 1):
        full_name = repo_info["nome_completo"]
        pos       = repo_info.get("posicao", "?")
        elapsed   = time.time() - t_start
        eta_str   = ""
        if idx > 1:
            per_repo = elapsed / (idx - 1)
            remaining = per_repo * (len(pending) - idx + 1)
            h, m = divmod(int(remaining), 3600)
            m //= 60
            eta_str = f" | ETA ~{h}h{m:02d}m"

        print(f"[{idx}/{len(pending)}] #{pos} {full_name}{eta_str}")

        with tempfile.TemporaryDirectory() as tmpdir:
            clone_dir  = Path(tmpdir) / "repo"
            ck_out_dir = Path(tmpdir) / "ck"

            # Clone
            try:
                print(f"  clone ...", end=" ", flush=True)
                clone_repo(full_name, clone_dir)
                print("OK")
            except subprocess.TimeoutExpired:
                print("TIMEOUT")
                log_error(f"{full_name} | clone | timeout")
                continue
            except subprocess.CalledProcessError as e:
                print(f"FALHOU ({e.returncode})")
                log_error(f"{full_name} | clone | {e}")
                continue

            # CK
            try:
                print(f"  CK    ...", end=" ", flush=True)
                class_csv = run_ck(clone_dir, ck_out_dir)
                print("OK")
            except subprocess.TimeoutExpired:
                print("TIMEOUT")
                log_error(f"{full_name} | ck | timeout")
                continue
            except subprocess.CalledProcessError as e:
                print(f"FALHOU")
                log_error(f"{full_name} | ck | {e.stderr.decode(errors='replace') if e.stderr else e}")
                continue

            if not class_csv.exists():
                print("  AVISO: class.csv não gerado, pulando.")
                log_error(f"{full_name} | ck | class.csv não encontrado")
                continue

            metrics = summarise(class_csv)

        # Releases (fora do tempdir — não precisa do código)
        releases = count_releases(full_name, args.token)

        row = {
            "posicao":      pos,
            "nome_completo": full_name,
            "estrelas":     repo_info.get("estrelas", ""),
            "idade_anos":   repo_info.get("idade_anos", ""),
            "total_releases": releases,
            **metrics,
        }
        writer.writerow(row)
        out_file.flush()
        ok += 1

        print(f"  classes={metrics['total_classes']} | "
              f"CBO={metrics['cbo_mediana']} | "
              f"DIT={metrics['dit_mediana']} | "
              f"LCOM={metrics['lcom_mediana']}")

    out_file.close()
    total_time = int(time.time() - t_start)
    h, rem = divmod(total_time, 3600)
    m, s   = divmod(rem, 60)
    print(f"\nConcluído: {ok}/{len(pending)} repositórios em {h}h{m:02d}m{s:02d}s")
    print(f"Resumo: {SUMMARY_CSV}")
    if ERROR_LOG.exists():
        errs = sum(1 for _ in open(ERROR_LOG))
        if errs:
            print(f"Erros  : {errs} entradas em {ERROR_LOG}")


if __name__ == "__main__":
    main()
