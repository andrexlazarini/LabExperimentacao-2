import argparse
import csv
import os
import sys
import time
import requests
from datetime import datetime, timezone

BASE_URL = "https://api.github.com/search/repositories"
OUTPUT_FILE = os.path.join(os.path.dirname(_file_), "..", "data", "repos.csv")

FIELDNAMES = [
    "posicao",
    "nome_completo",
    "url",
    "estrelas",
    "forks",
    "issues_abertas",
    "observadores",
    "tamanho_kb",
    "linguagem",
    "criado_em",
    "atualizado_em",
    "ultimo_push_em",
    "idade_anos",
    "url_releases",
    "branch_padrao",
    "descricao",
]


def get_headers(token: str | None) -> dict:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def age_in_years(created_at: str) -> float:
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return round((now - created).days / 365.25, 2)


def fetch_page(page: int, headers: dict) -> list[dict]:
    params = {
        "q": "language:Java",
        "sort": "stars",
        "order": "desc",
        "per_page": 100,
        "page": page,
    }
    for attempt in range(5):
        try:
            response = requests.get(BASE_URL, headers=headers, params=params, timeout=60)
            if response.status_code == 403:
                reset = int(response.headers.get("X-RateLimit-Reset", time.time() + 60))
                wait = max(reset - int(time.time()), 1) + 2
                print(f"  Limite de requisições atingido. Aguardando {wait}s ...", flush=True)
                time.sleep(wait)
                continue
            response.raise_for_status()
            data = response.json()
            return data.get("items", [])
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
            wait = 10 * (attempt + 1)
            print(f"  Erro de timeout/conexão (tentativa {attempt+1}/5). Tentando novamente em {wait}s ...", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"Falha ao buscar a página {page} após 5 tentativas")


def main():
    parser = argparse.ArgumentParser(description="Busca os top-1000 repositórios Java do GitHub.")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"), help="Token de acesso pessoal do GitHub")
    args = parser.parse_args()

    if not args.token:
        print("AVISO: Nenhum token do GitHub fornecido. O limite de requisições é de 10 por minuto sem autenticação.")
        print("Defina a variável de ambiente GITHUB_TOKEN ou use --token para limites maiores.\n")

    headers = get_headers(args.token)
    all_repos = []

    out_path = os.path.abspath(OUTPUT_FILE)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    start_page = 1
    if os.path.exists(out_path):
        with open(out_path, newline="", encoding="utf-8") as f:
            existing = list(csv.DictReader(f))
        if existing:
            all_repos.extend(existing)
            start_page = len(existing) // 100 + 1
            print(f"Retomando a partir da página {start_page} ({len(existing)} repositórios já salvos).")

    print("Buscando os top-1000 repositórios Java do GitHub...")
    with open(out_path, "a" if all_repos else "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not all_repos:
            writer.writeheader()

        for page in range(start_page, 11):
            print(f"  Página {page}/10 ...", end=" ", flush=True)
            items = fetch_page(page, headers)
            if not items:
                print("nenhum item retornado, encerrando.")
                break

            page_repos = []
            for rank_offset, repo in enumerate(items):
                posicao = (page - 1) * 100 + rank_offset + 1
                page_repos.append({
                    "posicao": posicao,
                    "nome_completo": repo["full_name"],
                    "url": repo["html_url"],
                    "estrelas": repo["stargazers_count"],
                    "forks": repo["forks_count"],
                    "issues_abertas": repo["open_issues_count"],
                    "observadores": repo["watchers_count"],
                    "tamanho_kb": repo["size"],
                    "linguagem": repo.get("language", ""),
                    "criado_em": repo["created_at"],
                    "atualizado_em": repo["updated_at"],
                    "ultimo_push_em": repo["pushed_at"],
                    "idade_anos": age_in_years(repo["created_at"]),
                    "url_releases": repo["releases_url"].replace("{/id}", ""),
                    "branch_padrao": repo["default_branch"],
                    "descricao": (repo.get("description") or "").replace("\n", " "),
                })

            writer.writerows(page_repos)
            f.flush()
            all_repos.extend(page_repos)
            print(f"obtidos {len(items)} repositórios (total até agora: {len(all_repos)})")

            if page < 10:
                time.sleep(1)

    print(f"\nConcluído! {len(all_repos)} repositórios salvos em {out_path}")


if _name_ == "_main_":
    main()
