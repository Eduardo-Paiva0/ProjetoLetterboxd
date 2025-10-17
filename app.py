from flask import Flask, render_template, request
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import requests
import os
import omdb
import re
from openai import OpenAI

# =============================
# 🔧 CONFIGURAÇÃO INICIAL
# =============================
load_dotenv()
app = Flask(__name__)

# Inicializa os clientes
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
omdb.set_default("apikey", os.getenv("OMDB_API_KEY"))


# =============================
# 🎬 SCRAPING DO LETTERBOXD
# =============================
def get_favorite_movies(username):
    """Busca os 4 filmes favoritos do perfil Letterboxd"""
    try:
        url = f"https://letterboxd.com/{username}/"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7",
        }
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            print("Status inesperado:", resp.status_code)
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        # Localiza a seção de favoritos
        h2 = None
        for tag in soup.find_all(["h2", "h3"]):
            if tag.get_text(strip=True).lower().startswith("favorite films"):
                h2 = tag
                break

        section = h2.find_parent(["section", "div"]) if h2 else None
        movies = []

        if section:
            imgs = section.find_all("img", alt=True)
            for img in imgs:
                alt = img.get("alt", "").strip()
                if alt and alt not in movies:
                    movies.append(alt)

            if len(movies) < 4:
                for li in section.select('li.poster-container[data-film-name]'):
                    name = li.get("data-film-name", "").strip()
                    if name and name not in movies:
                        movies.append(name)

        if len(movies) < 4:
            for li in soup.select('li.poster-container[data-film-name]'):
                name = li.get("data-film-name", "").strip()
                if name and name not in movies:
                    movies.append(name)
                if len(movies) >= 4:
                    break

        return movies[:4] if movies else None

    except Exception as e:
        print("Erro no scraping:", e)
        return None


# =============================
# 🎥 SCRAPING DOS FILMES ASSISTIDOS
# =============================
def get_watched_movies(username, max_pages=20):
    """
    Coleta os filmes marcados como 'assistidos' no Letterboxd.
    Compatível com o novo layout (div.film-poster[data-film-slug]).
    """
    watched = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7",
    }

    try:
        page = 1
        next_url = f"https://letterboxd.com/{username}/films/"
        while next_url and page <= max_pages:
            print(f"🔍 Coletando página {page}: {next_url}")
            resp = requests.get(next_url, headers=headers, timeout=15)
            if resp.status_code != 200:
                print(f"⚠️ Falha ao carregar página {page}: {resp.status_code}")
                break

            soup = BeautifulSoup(resp.text, "html.parser")

            # Novo seletor: <div class="film-poster" data-film-slug="/film/aftersun/">
            posters = soup.select("div.film-poster[data-film-slug]")
            films = []
            for div in posters:
                slug = div.get("data-film-slug", "").strip("/")
                if slug.startswith("film/"):
                    slug = slug.replace("film/", "").replace("-", " ")
                    film_name = slug.title()
                    films.append(film_name)

            # Fallback: <img alt="Nome do Filme">
            if not films:
                films = [img.get("alt", "").strip()
                         for img in soup.select("img[alt]") if img.get("alt")]

            watched.extend(films)

            # Paginação
            next_link = soup.select_one("a.next") or soup.find("a", rel="next")
            if next_link and next_link.get("href"):
                href = next_link.get("href")
                next_url = f"https://letterboxd.com{href}" if href.startswith("/") else href
                page += 1
            else:
                next_url = None

        # Remove duplicatas mantendo a ordem
        watched_unique = []
        seen = set()
        for w in watched:
            wl = w.lower()
            if wl not in seen:
                seen.add(wl)
                watched_unique.append(w)

        print(f"✅ {len(watched_unique)} filmes assistidos encontrados.")
        return watched_unique

    except Exception as e:
        print("❌ Erro ao buscar filmes assistidos:", e)
        return []



# =============================
# 🎞️ CONSULTA À OMDb API
# =============================
def get_movie_info(title):
    """Busca título, ano, pôster e IMDb ID usando OMDb"""
    try:
        api_key = os.getenv("OMDB_API_KEY")
        if not api_key:
            print("Chave OMDb não configurada.")
            return None

        match = re.match(r"(.+?)\s*\((\d{4})\)", title)
        if match:
            movie_title = match.group(1).strip()
            movie_year = match.group(2).strip()
        else:
            movie_title = title.strip()
            movie_year = None

        if movie_year:
            url = f"http://www.omdbapi.com/?apikey={api_key}&t={requests.utils.quote(movie_title)}&y={movie_year}"
        else:
            url = f"http://www.omdbapi.com/?apikey={api_key}&t={requests.utils.quote(movie_title)}"

        response = requests.get(url, timeout=10)
        data = response.json()

        if data.get("Response") == "False":
            print(f"❌ Filme não encontrado na OMDb: {title}")
            return None

        return {
            "title": data.get("Title"),
            "year": data.get("Year"),
            "poster": data.get("Poster") if data.get("Poster") != "N/A" else None,
            "imdb_id": data.get("imdbID"),
            "genre": data.get("Genre")
        }

    except Exception as e:
        print(f"⚠️ Erro OMDb ao buscar {title}: {e}")
        return None


# =============================
# 🌐 ROTAS FLASK
# =============================
@app.route('/')
def index():
    return render_template('index.html')


def clean_movie_title(raw_title):
    """Limpa o texto vindo da IA."""
    title = re.sub(r"^\d+[\).:\-]*\s*", "", raw_title)
    title = re.sub(r"[*_\"“”]", "", title)
    if "/" in title:
        title = title.split("/")[0]
    title = title.strip().strip(".").strip()
    return title


@app.route('/recommend', methods=['POST'])
def recommend():
    username = request.form.get('username')
    filter_watched = 'filter_watched' in request.form

    if not username:
        return render_template('index.html', error="Por favor, insira um nome de usuário válido.")

    favorite_movies = get_favorite_movies(username)
    if not favorite_movies:
        return render_template('index.html', error="Não foi possível encontrar os filmes favoritos. Verifique o nome do perfil ou se ele é público.")

    # --- Gera recomendações com IA (pool maior se filtro ativo) ---
    pool_size = 30 if filter_watched else 6
    prompt = f"""
    O usuário tem como filmes favoritos: {', '.join(favorite_movies)}.
    Gere exatamente {pool_size} recomendações de filmes que ele provavelmente vai gostar,
    baseando-se em semelhanças de tema, estética, narrativa e diretores.
    Responda APENAS com uma lista simples, cada linha contendo:
    "Título do filme (ano)" — sem explicações, sem frases introdutórias, sem numeração, sem negrito.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um curador de cinema. Sempre responde apenas com listas de filmes no formato 'Título (Ano)'."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )

        text = response.choices[0].message.content.strip()
        lines = [line.strip("•- \t") for line in text.split("\n") if line.strip()]
        clean_lines = [line for line in lines if re.search(r"\(\d{4}\)", line)]
        seen = set()
        recommendations_pool = []
        for r in (clean_movie_title(x) for x in clean_lines):
            rl = r.lower()
            if rl not in seen:
                seen.add(rl)
                recommendations_pool.append(r)

    except Exception as e:
        print("Erro na API da IA:", e)
        return render_template('index.html', error="Erro ao gerar recomendações. Tente novamente mais tarde.")

    # --- FILTRO: substituir apenas os já assistidos ---
    # --- FILTRO: substituir apenas os já assistidos ---
    if filter_watched:
        watched_movies = get_watched_movies(username)

        def normalize_title(title):
            # Remove ano
            title = re.sub(r"\(\d{4}\)", "", title)
            # Remove caracteres especiais e múltiplos espaços
            title = re.sub(r"[^a-zA-Z0-9\s]", "", title)
            # Normaliza espaços e case
            title = re.sub(r"\s+", " ", title).strip().lower()
            return title

        # Conjunto normalizado de filmes assistidos
        watched_normalized = {normalize_title(w) for w in watched_movies}

        unseen = []
        for r in recommendations_pool:
            norm = normalize_title(r)
            if norm not in watched_normalized:
                unseen.append(r)
            else:
                print(f"🚫 Removido (já assistido): {r}")

        # Garante 6 inéditos (ou preenche se faltar)
        recommendations = unseen[:6] if len(unseen) >= 6 else (
            unseen + [r for r in recommendations_pool if normalize_title(r) not in {normalize_title(x) for x in unseen}]
        )[:6]

        print(f"🎯 {len(unseen)} inéditos; entregues {len(recommendations)} após substituição de vistos.")
    else:
        recommendations = recommendations_pool[:6]


    # --- Enriquecer com dados da OMDb ---
    favorite_info = [get_movie_info(m) or {"title": m, "year": "", "poster": None, "imdb_id": None, "genre": ""} for m in favorite_movies]
    recommend_info = [get_movie_info(m) or {"title": m, "year": "", "poster": None, "imdb_id": None, "genre": ""} for m in recommendations]

    # --- Renderiza página ---
    return render_template(
        'results.html',
        username=username,
        favorites=favorite_info,
        recommendations=recommend_info,
        filter_watched=filter_watched
    )


# =============================
# ▶️ EXECUÇÃO LOCAL
# =============================
if __name__ == '__main__':
    app.run(debug=True)
