import argparse
import csv
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPOS_CSV = ROOT / "data" / "repos.csv"
RESULTS_DIR = ROOT / "results"
SUMMARY_CSV = RESULTS_DIR / "metrics_summary.csv"
CK_JAR = ROOT / "ck.jar"

CK_JAR_URL = (
    "https://github.com/mauricioaniche/ck/releases/download/v0.7.1/"
    "ck-0.7.1-SNAPSHOT-jar-with-dependencies.jar"
)

SUMMARY_FIELDS = [
    "posicao",
    "nome_completo",
    "estrelas",
    "idade_anos",
    "total_releases",
    "cbo_mediana", "cbo_media", "cbo_desvio",
    "dit_mediana", "dit_media", "dit_desvio",
    "lcom_mediana", "lcom_media", "lcom_desvio",
    "loc_mediana", "loc_media", "loc_total",
    "comentarios_mediana", "comentarios_media", "comentarios_total",
    "total_classes",
]


def ensure_ck_jar():
    if CK_JAR.exists():
        return
    print(f"CK jar não encontrado. Baixando do GitHub releases...")
    print(f"  URL : {CK_JAR_URL}")
    print(f"  Dest: {CK_JAR}")
    urllib.request.urlretrieve(CK_JAR_URL, CK_JAR)
    print("  Download concluído.")


def count_releases(full_name: str, token: str | None = None) -> int:
    import urllib.request as ur
    import json

    url = f"https://api.github.com/repos/{full_name}/releases?per_page=1"
    req = ur.Request(url, headers={"Accept": "application/vnd.github+json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with ur.urlopen(req, timeout=10) as resp:
            # GitHub retorna o header Link com o número da última página
            link = resp.headers.get("Link", "")
            if 'rel="last"' in link:
                import re
                m = re.search(r'page=(\d+)>; rel="last"', link)
                if m:
                    return int(m.group(1))
            data = json.loads(resp.read())
            return len(data)
    except Exception:
        return -1


def clone_repo(full_name: str, dest: Path):
    url = f"https://github.com/{full_name}.git"
    subprocess.run(
        ["git", "clone", "--depth", "1", "--quiet", url, str(dest)],
        check=True,
        timeout=300,
    )

def run_ck(repo_dir: Path, output_dir: Path) -> Path:
    """Executa o CK em repo_dir, salvando os CSVs em output_dir. Retorna o caminho para class.csv."""
    output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "java", "-jar", str(CK_JAR),
            str(repo_dir),
            "false",
            "0",
            "false",
            str(output_dir) + os.sep,
        ],
        check=True,
        timeout=600,
        capture_output=True,
    )
    return output_dir / "class.csv"


def summarise_class_csv(class_csv: Path) -> dict:
    cbo_vals, dit_vals, lcom_vals, loc_vals, comments_vals = [], [], [], [], []

    with open(class_csv, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                cbo_vals.append(float(row["cbo"]))
                dit_vals.append(float(row["dit"]))
                lcom_vals.append(float(row.get("lcom", row.get("lcom*", 0))))
                loc_vals.append(float(row["loc"]))
                comments_vals.append(float(row.get("returnQty", 0)))
                for comment_key in ("comments", "commentLines", "comment"):
                    if comment_key in row:
                        comments_vals[-1] = float(row[comment_key])
                        break
            except (ValueError, KeyError):
                continue

    def stats(vals):
        if not vals:
            return 0.0, 0.0, 0.0
        median = statistics.median(vals)
        mean = round(statistics.mean(vals), 4)
        std = round(statistics.stdev(vals) if len(vals) > 1 else 0.0, 4)
        return round(median, 4), mean, std

    cbo_med, cbo_mean, cbo_std = stats(cbo_vals)
    dit_med, dit_mean, dit_std = stats(dit_vals)
    lcom_med, lcom_mean, lcom_std = stats(lcom_vals)
    loc_med, loc_mean, _ = stats(loc_vals)
    com_med, com_mean, _ = stats(comments_vals)

    return {
        "cbo_mediana": cbo_med, "cbo_media": cbo_mean, "cbo_desvio": cbo_std,
        "dit_mediana": dit_med, "dit_media": dit_mean, "dit_desvio": dit_std,
        "lcom_mediana": lcom_med, "lcom_media": lcom_mean, "lcom_desvio": lcom_std,
        "loc_mediana": loc_med, "loc_media": loc_mean, "loc_total": round(sum(loc_vals), 0),
        "comentarios_mediana": com_med, "comentarios_media": com_mean,
        "comentarios_total": round(sum(comments_vals), 0),
        "total_classes": len(cbo_vals),
    }


def main():
    parser = argparse.ArgumentParser(description="Clona repositórios e coleta métricas CK.")
    parser.add_argument("--repo", help="Repositório único (owner/nome) a processar")
    parser.add_argument("--limit", type=int, default=None, help="Número máximo de repositórios a processar do repos.csv")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--skip-clone", action="store_true", help="Pular a clonagem (usar clone existente em results/)")
    args = parser.parse_args()

    ensure_ck_jar()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.repo:
        repos = [{"posicao": 1, "nome_completo": args.repo, "estrelas": "?", "idade_anos": "?"}]
    else:
        if not REPOS_CSV.exists():
            print(f"ERRO: {REPOS_CSV} não encontrado. Execute fetch_repos.py primeiro.", file=sys.stderr)
            sys.exit(1)
        with open(REPOS_CSV, newline="", encoding="utf-8") as f:
            repos = list(csv.DictReader(f))
        if args.limit:
            repos = repos[: args.limit]

    write_header = not SUMMARY_CSV.exists()
    summary_file = open(SUMMARY_CSV, "a", newline="", encoding="utf-8")
    summary_writer = csv.DictWriter(summary_file, fieldnames=SUMMARY_FIELDS)
    if write_header:
        summary_writer.writeheader()

    print(f"Processando {len(repos)} repositórios...\n")

    for i, repo_info in enumerate(repos, 1):
        full_name = repo_info["nome_completo"]
        safe_name = full_name.replace("/", "__")
        repo_result_dir = RESULTS_DIR / safe_name

        print(f"[{i}/{len(repos)}] {full_name}")

        with tempfile.TemporaryDirectory() as tmpdir:
            clone_dir = Path(tmpdir) / "repo"
            if not args.skip_clone:
                try:
                    print(f"  Clonando ...", end=" ", flush=True)
                    clone_repo(full_name, clone_dir)
                    print("concluído.")
                except subprocess.CalledProcessError as e:
                    print(f"FALHOU (clone): {e}")
                    continue
            else:
                clone_dir = repo_result_dir / "repo"
                if not clone_dir.exists():
                    print(f"  Nenhum repositório pré-clonado encontrado em {clone_dir}, pulando.")
                    continue

            ck_output_dir = repo_result_dir / "ck_output"
            try:
                print(f"  Executando CK ...", end=" ", flush=True)
                class_csv = run_ck(clone_dir, ck_output_dir)
                print("concluído.")
            except subprocess.CalledProcessError as e:
                print(f"FALHOU (CK): {e.stderr.decode() if e.stderr else e}")
                continue
            except FileNotFoundError:
                print(f"FALHOU: CK não gerou class.csv em {ck_output_dir}")
                continue

            if not class_csv.exists():
                print(f"  AVISO: class.csv não encontrado em {ck_output_dir}, pulando.")
                continue

            metrics = summarise_class_csv(class_csv)

            releases = count_releases(full_name, args.token)

            row = {
                "posicao": repo_info.get("posicao", i),
                "nome_completo": full_name,
                "estrelas": repo_info.get("estrelas", ""),
                "idade_anos": repo_info.get("idade_anos", ""),
                "total_releases": releases,
                **metrics,
            }
            summary_writer.writerow(row)
            summary_file.flush()

            print(f"  Classes: {metrics['total_classes']} | "
                  f"CBO mediana={metrics['cbo_mediana']} | "
                  f"DIT mediana={metrics['dit_mediana']} | "
                  f"LCOM mediana={metrics['lcom_mediana']}")

    summary_file.close()
    print(f"\nResumo salvo em {SUMMARY_CSV}")


if __name__ == "__main__":
    main()
