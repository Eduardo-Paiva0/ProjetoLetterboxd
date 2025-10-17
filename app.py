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
# 🎞️ CONSULTA À OMDb API
# =============================
def get_movie_info(title):
    """
    Busca título, ano, pôster e IMDb ID usando OMDb,
    incluindo suporte a títulos com ano no formato 'Nome (2020)'.
    """
    try:
        api_key = os.getenv("OMDB_API_KEY")
        if not api_key:
            print("Chave OMDb não configurada.")
            return None

        # Extrai título e ano, se houver
        match = re.match(r"(.+?)\s*\((\d{4})\)", title)
        if match:
            movie_title = match.group(1).strip()
            movie_year = match.group(2).strip()
        else:
            movie_title = title.strip()
            movie_year = None

        # Monta URL com título e ano (quando disponível)
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
    """
    Limpa o texto vindo do GPT, removendo caracteres extras, múltiplos títulos, etc.
    """
    import re
    # Remove numeração e negrito
    title = re.sub(r"^\d+[\).:\-]*\s*", "", raw_title)
    title = re.sub(r"[*_\"“”]", "", title)

    # Mantém apenas o primeiro título antes de uma barra, se houver múltiplos
    if "/" in title:
        title = title.split("/")[0]

    # Remove espaços duplos e pontuação no fim
    title = title.strip().strip(".").strip()
    return title


@app.route('/recommend', methods=['POST'])
def recommend():
    username = request.form.get('username')

    if not username:
        return render_template('index.html', error="Por favor, insira um nome de usuário válido.")

    # --- Busca filmes favoritos ---
    favorite_movies = get_favorite_movies(username)
    if not favorite_movies:
        return render_template('index.html', error="Não foi possível encontrar os filmes favoritos. Verifique o nome do perfil ou se ele é público.")

    # --- Gera recomendações com OpenAI ---
    prompt = f"""
    O usuário tem como filmes favoritos: {', '.join(favorite_movies)}.
    Gere exatamente 6 recomendações de filmes que ele provavelmente vai gostar,
    baseando-se em semelhanças de tema, estética, narrativa e diretores.
    Responda APENAS com uma lista simples, cada linha contendo:
    "Título do filme (ano)" — sem explicações, sem frases introdutórias, sem numeração, sem negrito.

    Exemplo de formato esperado:
    Her (2013)
    The Fountain (2006)
    The Fall (2006)
    Spirited Away (2001)
    The Matrix (1999)
    Blade Runner 2049 (2017)
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

        # Pega o texto bruto da IA
        text = response.choices[0].message.content.strip()

        # Divide o texto em linhas, ignora vazios
        lines = [line.strip("•- \t") for line in text.split("\n") if line.strip()]

        # Remove linhas que não parecem filmes (por segurança)
        clean_lines = [line for line in lines if re.search(r"\(\d{4}\)", line)]

        # Limpa caracteres especiais
        recommendations = [clean_movie_title(r) for r in clean_lines]

    except Exception as e:
        print("Erro na API da OpenAI:", e)
        return render_template('index.html', error="Erro ao gerar recomendações. Tente novamente mais tarde.")

    # --- Enriquecer com dados da OMDb ---
    favorite_info = []
    for m in favorite_movies:
        info = get_movie_info(m)
        favorite_info.append(info or {"title": m, "year": "", "poster": None, "imdb_id": None})

    recommend_info = []
    for m in recommendations:
        info = get_movie_info(m)
        recommend_info.append(info or {"title": m, "year": "", "poster": None, "imdb_id": None})

    # --- Renderiza página ---
    return render_template('results.html',
                           username=username,
                           favorites=favorite_info,
                           recommendations=recommend_info)


# =============================
# ▶️ EXECUÇÃO LOCAL
# =============================
if __name__ == '__main__':
    app.run(debug=True)
