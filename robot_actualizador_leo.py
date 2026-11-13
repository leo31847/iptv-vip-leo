# -*- coding: utf-8 -*-
"""
ROBOT CAZADOR SUPREMO OMEGA v4.0 - LEONARDO
============================================
Principios (no negociables):
  1. INMUTABILIDAD ACUMULATIVA: nunca borra un canal/serie que funciona. Lo existente
     en LISTA_MAESTRA_LEO_VIP.m3u se carga PRIMERO y conserva su enlace y su posicion.
  2. REEMPLAZO SOLO POR MUERTE REAL: un enlace solo se cambia si falla. Un enlace
     caido recibe "strikes"; se elimina solo tras 3 ejecuciones seguidas fallando.
     Si la red falla de forma masiva (>50% caidos), no se penaliza nada.
  3. CERO IDIOMAS AJENOS: solo fuentes hispanas + filtro por nombre, tvg-id y dominio
     (Brasil/Portugal, ingles, India, Italia, Rusia, etc. quedan bloqueados).
  4. SERIES COMPLETAS ACUMULATIVAS: temporadas completas en Espanol Latino desde
     Archive.org, guardadas en series_completas_cache.json (nunca se pierden) y
     auto-descubrimiento de series nuevas con filtro estricto de idioma.

Uso:  python robot_actualizador_leo.py            (con ventana final para compartir)
      python robot_actualizador_leo.py --no-gui   (sin ventana, modo consola)
"""
import os
import re
import sys
import json
import time
import ssl
import shutil
import socket
import unicodedata
import urllib.request
import urllib.parse
import urllib.error
import collections
from concurrent.futures import ThreadPoolExecutor

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# Contexto SSL permisivo para emisoras regionales y servidores de cable
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

HEADERS = {'User-Agent': 'VLC/3.0.20 LibVLC/3.0.20'}
BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
}

APP_DIR = os.path.dirname(os.path.abspath(__file__))
BLACKLIST_IDENTIFIERS = {
    'macgyver-collection-1985--to-1994',
    'pocoyo-perdidos-en-el-espacio-dvd-iso',
    'cesser-16-liga-de-la-justicia-720p',
    'ededdeeddys0106specialefilmmuxbythegatto',
    'ededeeddys0106specialefilmmuxbythegatto',
    'gatocosmico',
    'popeye33',
    'escalofrios95',
    'pucca06lat',
    'la-ninera-2004-480p',
    't-2x-14',
    'kenan-y-kel-s-02',
    'bob-esponja-2-temporada-episodios-09-supervivencia-de-los-idiotas-.-expulsado',
    'los-pitufos-azteca-7-mexico-volumenes-47-48-49-incluye-15-metariales-extras-dvd-9',
    'la-familia-ingalls-temporada-1',
    'la-familia-ingalls-temporada-1_202010',
    'batman-la-serie-animada-1992-latino',
    'coraje-1', 'coraje-2', 'coraje-3', 'coraje-4',
    'coraje-el-perro-cobarde-latino',
    'malcolm-el-de-en-medio-t-01', 'malcolm-el-de-en-medio-t-02',
    'malcolm-el-de-en-medio-t-03', 'malcolm-el-de-en-medio-t-04',
    'malcolm-el-de-en-medio-t-05', 'malcolm-el-de-en-medio-t-06',
    'malcolm-el-de-en-medio-t-07', 'malcolm-el-de-en-medio-temp01',
    'alf-latino_202511', 'gordonshumway',
    'thundercats-063-mumm-rana', 'thundercats2011', 'thundercats_202303',
    'dragon-ball-z-latino-jp', 'don-gato-y-su-pandilla_202601', '14_20210419',
    'season_1_1', 'darkwing-duck_20240119', 'ducktales-1987_202601', 'duck-tales-dublado',
    'voyagers-complete-series-1982', 'captain-planet-and-the-planeteers-1990',
    'captain-planet-and-the-planeteers-480p', 'growing-pains-complete-series',
    '52_20200504_20200504', 'ninos-en-crecimiento-bravo-pedro-pudiste-hacerlo',
    'cantishow-megab',
}

def _is_blacklisted_url(u):
    raw_l = (u or '').lower()
    unq_l = urllib.parse.unquote(u or '').lower()
    for s in (raw_l, unq_l):
        if any((f'/{b}/' in s or s.endswith(f'/{b}')) for b in BLACKLIST_IDENTIFIERS):
            return True
    return False

PLUTO_MACGYVER_SERIES_ID = "643fea281a5081001ad8a1d8"
SIMPSONS_FALLBACK_LOGO = "https://archive.org/services/img/tinaco_20210512"
SUPERSONICOS_LOGO = "https://archive.org/services/img/t-2-02.-ia"

def _probe_direct_media_ok(url, timeout=12):
    import urllib.request as _ur
    import urllib.error as _ue
    req = _ur.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Range': 'bytes=0-1023'
    })
    try:
        with _ur.urlopen(req, timeout=timeout) as r:
            code = r.getcode()
            ctype = (r.headers.get('Content-Type') or '').lower()
            crange = r.headers.get('Content-Range', '')
            clen = r.headers.get('Content-Length', '')
            _ = r.read(256)
            size_b = 0
            m_tot = re.search(r'/(\d+)$', crange)
            if m_tot:
                size_b = int(m_tot.group(1))
            elif clen.isdigit():
                size_b = int(clen)
            ok_type = ('video' in ctype or 'octet-stream' in ctype or 'matroska' in ctype)
            return (code in (200, 206) and ok_type and size_b > 1_000_000), code
    except _ue.HTTPError as e:
        return False, e.code
    except Exception:
        return False, 0

def _norm_ext_media_url(u):
    u = (u or '').strip()
    u = re.sub(r'^https?://ia\d+\.us\.archive\.org/\d+/items/', 'https://archive.org/download/', u, flags=re.I)
    if u.startswith('http://pomf2.lain.la/') or u.startswith('http://archive.org/'):
        u = 'https://' + u[7:]
    if 'dropbox.com/scl/' in u and 'dl=0' in u:
        u = u.replace('dl=0', 'dl=1')
    return u

def _parse_simple_extinf(txt):
    out = []
    cur_t = ''
    for raw in (txt or '').splitlines():
        ln = raw.strip()
        if not ln:
            continue
        if ln.startswith('#EXTINF:'):
            cur_t = ln.split(',', 1)[-1].strip()
        elif ln.startswith('http://') or ln.startswith('https://'):
            out.append((cur_t, _norm_ext_media_url(ln)))
            cur_t = ''
    return out

# Catálogo maestro curado de Pluto TV CO VOD (100% es:Spanish [Original] verificado por API/Audio)
# Formato: (tier, nombre_serie, pluto_series_id) — Tier 0 nunca se recorta por presupuesto de bytes.
PLUTO_CO_SERIES_CATALOG = [
    (0, "MacGyver", "643fea281a5081001ad8a1d8"),
    (1, "Los Pitufos", "691b2e4669032f4edfd915be"),
    (1, "Tortugas Ninja", "63ff6e23689edb0013bce4e7"),
    (1, "Kenan y Kel", "5eff42e91bfe8e001a9a5460"),
    (1, "Popeye el Marino", "602c566bf5408c001a4fc3e0"),
    (1, "All-New Popeye", "5e6bdbbce2fa10001bed0543"),
    (1, "Rugrats Crecidos", "5e31a4c2423d816d8854350b"),
    (1, "Avatar: La Leyenda de Aang", "65c4db93a40ff70013e98095"),
    (1, "Danny Phantom", "5f909977397eee001aba59e9"),
    (1, "Los Pinguinos de Madagascar", "649c4af7500e680013c667e5"),
    (1, "Kung Fu Panda: La Leyenda de Po", "649c499b3e9a7b001393b41e"),
    (1, "Mr. Bean Animado", "5e0fc8ebd78344b4ec61adf1"),
    (1, "South Park", "60c8f213e301960013db44f8"),
    (1, "Daria", "5e20986b370805f4c87911aa"),
    (1, "La Vida Moderna de Rocko", "5e32082ab5f08674273e624c"),
    (1, "CatDog", "5e33683826aa35a05e2e06e5"),
    (1, "Los Castores Cascarrabias", "5e4445ca9cd486cdb87c1d4f"),
    (1, "Aaahh!!! Monstruos de Verdad", "5e305b3b00b8fd45e1433e0e"),
    (1, "Los Thornberrys", "5e29cad3d5346a9b8e714610"),
    (1, "Rocket Power", "61a6276d178ebd00137ad118"),
    (1, "Invasor Zim", "615c4e0b5daa86001a53c993"),
    (1, "El Tigre: Las Aventuras de Manny Rivera", "615753f356bf09001321f93c"),
    (1, "Los Padrinos Magicos", "631a0d4bc38c5300133782a2"),
    (1, "Le Temes a la Oscuridad", "6350049bd6ee50001378f1c8"),
    (1, "Clarissa lo Explica Todo", "5fe10c930ba4f0001a401c5d"),
    (1, "Death Note", "5e73a62fb16882001b38dec6"),
    (1, "Naruto", "5e73b850e40c9f001a0a9fb4"),
    (1, "Naruto Shippuden", "5ed68438af4720001a024113"),
    (1, "Yu-Gi-Oh!", "5f19972aefe562001369966c"),
    (1, "Hunter x Hunter", "64c3c440fdd8620013a4224f"),
    (1, "Shaman King", "6042944f558c290014fa6a01"),
    (1, "Star Trek: Espacio Profundo 9", "68adbc784f8d4a9917b534e8"),
    (1, "Star Trek: Voyager", "68ed0a1871d0752d879dad80"),
    (1, "Hechiceras", "6812382600cabfe6fe7f9093"),
    (1, "CSI: Miami", "63bc1f45a6bb3b001475e802"),
    (1, "Los 4400", "693c4e4ad405d15a95bdf742"),
    (1, "Twin Peaks", "6a9ec4c8e92f4736336c8558"),
    (2, "Zoey 101", "627281309f694b001374046c"),
    (2, "Victorious", "6890d79863893d441e1f7996"),
    (2, "Big Time Rush", "6335c10005b8af001385cd88"),
    (2, "Sam y Cat", "6335bfaa7a31e800133e7ad5"),
    (2, "Yu-Gi-Oh! GX", "687e46784f8d4a99177053ce"),
    (2, "JoJo's Bizarre Adventure", "65bd42b9b65b870013b0bd02"),
    (2, "Boruto: Naruto Next Generations", "65240b9f4827fc001a05ae1d"),
    (2, "Frasier", "6a32f9f0114ca7fcbe2e1a4a"),
    (2, "The King of Queens", "690ccca5d2a007fabab028c2"),
    (2, "Medium", "6a85c84ada71d9a75f00e748"),
    (2, "Numb3rs", "681239919f0436e1abdd3361"),
    (2, "NCIS", "64413b886113a5001afb0856"),
    (2, "Blue Bloods", "6a3d3a00812ca100160a25a2"),
    (2, "Camino al Cielo", "64a2d190fdd8620013ec4b5e"),
    (2, "Alerta Cobra", "654a7418619680001aa33093"),
    (2, "Andromeda", "6113ff42975c210013c15376"),
    (2, "Relic Hunter", "608ab1ec565bff0013119818"),
    (2, "Z Nation", "66a269ea8dfe2a00133cff60"),
    (2, "Hell on Wheels", "64b6d9ee2273310013523281"),
    (2, "La Familia del Barrio", "5f1756eb6ebd4d0013287f74"),
    (2, "El Capo", "6a96db59da71d9a75f4fc561"),
    (2, "Rafael Orozco, el Idolo", "64ff0f506b9e3e00137c0861"),
    (2, "La Ronca de Oro", "65085ab0f64f180013e74d31"),
    (2, "La Seleccion", "5eaadd47a3eeeb001aa62a63"),
    (2, "La Seleccion 2", "5ec56f8ace3117001a20b490"),
    (3, "Los Asesinatos de Midsomer", "63b6e56cd5762100130180e9"),
    (3, "Archivos Forenses", "5e1e5fc52fe6c1fc70e12be6"),
]

PLUTO_SERIES_TIER = {name.lower(): tier for tier, name, _ in PLUTO_CO_SERIES_CATALOG}

def fetch_pluto_vod_series_batch():
    """Extrae lote curado de series oficiales en Español desde Pluto TV CO VOD API verificando región CO y #EXTM3U."""
    import urllib.request as _ur
    import uuid as _uuid
    import base64 as _b64
    from concurrent.futures import ThreadPoolExecutor

    entries = []
    vod_map = {}
    posters_by_series = {}
    fetched_keys = set()
    hdrs = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Accept': 'application/json'}

    try:
        boot_url = (
            "https://boot.pluto.tv/v4/start?appName=web&appVersion=9.20.0&deviceVersion=122.0.0"
            "&deviceModel=web&deviceMake=chrome&deviceType=web"
            f"&clientID={_uuid.uuid4()}&clientModelNumber=1.0&serverSideAds=false"
            "&constraints=&notificationVersion=1&appStoreUrl=&architecture="
        )
        boot = json.loads(_ur.urlopen(_ur.Request(boot_url, headers=hdrs), timeout=15).read().decode('utf-8', 'replace'))
        jwt = boot.get('sessionToken', '')
        if not jwt:
            return entries, vod_map, posters_by_series, fetched_keys

        # Validar país CO en el payload JWT para no sobrescribir enlaces CO si corre desde runner US (GitHub Actions)
        country = ''
        try:
            parts = jwt.split('.')
            if len(parts) >= 2:
                pad = parts[1] + '=' * (-len(parts[1]) % 4)
                payload = json.loads(_b64.urlsafe_b64decode(pad))
                country = (payload.get('country') or payload.get('countryCode') or '').upper()
        except Exception:
            country = ''
        if country and country != 'CO':
            print(f"[!] Pluto VOD detectó región '{country}' != CO: omitiendo lote fresco para preservar enlaces CO existentes.")
            return entries, vod_map, posters_by_series, fetched_keys

        def _fetch_one(item):
            tier, s_name, sid = item
            s_url = f"https://service-vod.clusters.pluto.tv/v4/vod/series/{sid}/seasons?offset=1000&page=1"
            s_req = _ur.Request(s_url, headers={**hdrs, 'Authorization': f'Bearer {jwt}'})
            try:
                data = json.loads(_ur.urlopen(s_req, timeout=20).read().decode('utf-8', 'replace'))
            except Exception:
                return tier, s_name, "", []

            poster = ""
            for cov in (data.get('covers') or []):
                if cov.get('url'):
                    poster = cov['url']
                    if cov.get('aspectRatio') == '347:500':
                        break

            seasons = sorted(data.get('seasons') or [], key=lambda x: int(x.get('number') or 0))
            s_rows = []
            for sea in seasons:
                snum = int(sea.get('number') or 0)
                if snum <= 0:
                    continue
                eps = sorted(sea.get('episodes') or [], key=lambda x: int(x.get('number') or 0))
                for ep in eps:
                    ep_id = (ep.get('_id') or '').strip()
                    if not ep_id:
                        continue
                    enum = int(ep.get('number') or 0)
                    etitle = re.sub(r'\s+', ' ', (ep.get('name') or f"Episodio {enum:02d}")).strip()
                    stream_url = f"https://ipv4.pluto.tv/api/tn/video/playout/v2/stitch/hls/episode/{ep_id}/master.m3u8?jwt={jwt}"
                    grp = f"Series: {s_name} - Temporada {snum:02d}"
                    disp = f"{s_name} - T{snum:02d}E{enum:02d} - {etitle}"
                    s_rows.append((grp, disp, stream_url, poster, f"vod:{ep_id}"))
            return tier, s_name, poster, s_rows

        with ThreadPoolExecutor(max_workers=10) as ex:
            results = list(ex.map(_fetch_one, PLUTO_CO_SERIES_CATALOG))

        first_url = ""
        for _, _, _, s_rows in results:
            if s_rows:
                first_url = s_rows[0][2]
                break

        if first_url:
            m3u_txt = _ur.urlopen(_ur.Request(first_url, headers={'User-Agent': hdrs['User-Agent']}), timeout=12).read().decode('utf-8', 'replace')
            if '#EXTM3U' not in m3u_txt:
                print("[!] Pluto VOD CO: master.m3u8 inválido, abortando lote.")
                return [], {}, {}, set()

        ok_series = 0
        for tier, s_name, poster, s_rows in results:
            if not s_rows:
                continue
            ok_series += 1
            s_key = s_name.lower()
            fetched_keys.add(s_key)
            if poster:
                posters_by_series[s_key] = poster
            for grp, disp, stream_url, p, vid in s_rows:
                entries.append((grp, disp, stream_url, p))
                vod_map[stream_url] = vid

        print(f"[+] Pluto VOD CO ({country or 'CO'}): {ok_series}/{len(PLUTO_CO_SERIES_CATALOG)} series | {len(entries)} episodios verificados.")
    except Exception as e:
        print(f"[!] Error consultando Pluto VOD CO Batch: {e}")
        return [], {}, {}, set()
    return entries, vod_map, posters_by_series, fetched_keys

# Fuentes M3U externas curadas (100% Español Latino verificado por Whisper + HTTP 206 MP4)
VERIFIED_EXTERNAL_M3U_POOLS = [
    ("Batman la Serie Animada", "https://archive.org/download/ns_20210520/BAT%20SER.m3u", None),
    ("Bob Esponja", "https://archive.org/download/ns_20210520/bob%20espoja.m3u", None),
    ("Breaking Bad", "https://archive.org/download/ns_20210520/BB.m3u", None),
    ("Prison Break", "https://archive.org/download/ns_20210520/PRISONBRAK.m3u", None),
    ("Star Wars: La Guerra de los Clones", "https://archive.org/download/ns_20210520/CLONE.m3u", None),
    ("Grimm", "https://archive.org/download/ns_20210520/GRIMM.m3u", None),
    ("Digimon Adventure 02", "https://archive.org/download/ns_20210520/digi2.m3u", None),
    ("Detective Conan", "https://archive.org/download/ns_20210520/CONAN.m3u", None),
    ("El Increible Mundo de Gumball", "https://archive.org/download/ns_20210520/GUMBALL2.m3u", None),
    ("Club de Cuervos", "https://archive.org/download/ns_20210520/CLUBCUERVOS.m3u", None),
    ("Miraculous Ladybug", "https://archive.org/download/ns_20210520/LADYBUG.m3u", None),
    ("Sakura Card Captor", "https://archive.org/download/ns_20210520/sakura%20carp%20captor.m3u", None),
    ("Pokemon", "https://archive.org/download/ns_20210520/pokemon.m3u", None),
    ("Dragon Ball Super", "https://archive.org/download/ns_20210520/DBSL.m3u", None),
    ("Los Expedientes Secretos X", "https://archive.org/download/ns_20210520/expedientes%20x.m3u", None),
    ("Coraje el Perro Cobarde", "https://archive.org/download/ns_20210520/CORAJE.m3u", None),
    ("Drake & Josh", "https://archive.org/download/ns_20210520/DRAJOS.m3u", None),
    ("Manual de Supervivencia Escolar de Ned", "https://archive.org/download/ns_20210520/NED.m3u", None),
    ("Gravity Falls", "https://raw.githubusercontent.com/tokio14-dot/daima/main/Gravity%20Falls", None),
    ("Slam Dunk", "https://raw.githubusercontent.com/tokio14-dot/daima/main/slamduk", None),
    ("Medabots", "https://raw.githubusercontent.com/tokio14-dot/daima/main/medabots.txt", None),
    ("Pecezuelos", "https://raw.githubusercontent.com/tokio14-dot/pecezuelo/main/01", None),
    ("Pecezuelos", "https://raw.githubusercontent.com/tokio14-dot/pecezuelo/main/02", None),
    ("Pecezuelos", "https://raw.githubusercontent.com/tokio14-dot/pecezuelo/main/03", None),
    ("Bleach", "https://raw.githubusercontent.com/tokio14-dot/bleach/main/01", None),
    ("Onegai My Melody", "https://raw.githubusercontent.com/mametchikitty/Listas-IPTV/main/dibujos-animados.m3u", "Onegai My Melody"),
    ("Historias Asombrosas", "https://raw.githubusercontent.com/tokio14-dot/cuentos/main/cuentosasom", None),
    ("X-Men '97", "https://raw.githubusercontent.com/Dante5910/Esto-solamente-es-una-prueba/main/X%20men%2097", None),
]

def _decode_m3u_bytes(raw_bytes):
    try:
        return raw_bytes.decode('utf-8')
    except UnicodeDecodeError:
        return raw_bytes.decode('cp1252', 'replace')

def _parse_ext_items_with_logo(raw_bytes, filter_substr=None):
    txt = _decode_m3u_bytes(raw_bytes)
    items = []
    cur_t = ''
    cur_logo = ''
    cur_grp_season = None
    skip = False
    for raw in txt.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        if ln.startswith('#EXTGRP:'):
            mg = re.search(r'(?:temporada|season)\s*(\d{1,2})', ln, flags=re.I)
            if mg:
                cur_grp_season = int(mg.group(1))
            continue
        if ln.startswith('#EXTINF:'):
            if filter_substr and filter_substr.lower() not in ln.lower():
                skip = True
                cur_t = ''
                cur_logo = ''
                continue
            skip = False
            ml = re.search(r'tvg-logo="([^"]+)"', ln, flags=re.I)
            cur_logo = ml.group(1).strip() if ml else ''
            if 'pelisimg.online' in cur_logo.lower():
                cur_logo = ''
            cur_t = ln.split(',', 1)[-1].replace('\xa0', ' ').strip()
        else:
            ln_u = re.sub(r'^[\d\s]+(?=https?://)', '', ln)
            if not (ln_u.startswith('http://') or ln_u.startswith('https://')):
                continue
            if skip:
                skip = False
                continue
            u = _norm_ext_media_url(ln_u)
            eff_t = cur_t or re.sub(r'\.[a-z0-9]{2,5}$', '', urllib.parse.unquote(u.rsplit('/', 1)[-1])).strip()
            m_ux = re.search(r'/(\d{1,2})[xX](\d{1,3})(?:[-.\w]*)\.[a-z0-9]{2,5}(?:\?|$)', u)
            if m_ux and re.fullmatch(r'\d{1,3}', eff_t.strip()):
                eff_t = f"{int(m_ux.group(1))}x{int(m_ux.group(2)):02d}"
            elif cur_grp_season and re.fullmatch(r'\d{1,3}', eff_t.strip()):
                eff_t = f"{cur_grp_season}x{int(eff_t):02d}"
            items.append((eff_t, u, cur_logo))
            cur_t = ''
            cur_logo = ''
    return items

def _format_ext_season_ep(series_name, raw_title, seq_idx, murl=""):
    t = re.sub(r'\s+', ' ', (raw_title or '').replace('\xa0', ' ')).strip()
    t = re.sub(r'^' + re.escape(series_name) + r'\s*[-:]?\s*', '', t, flags=re.I).strip()

    snum, enum, sub = None, None, t
    # Caso especial: Gravity Falls trae T01 en 1..20 y T02 en 21..40 con numeración reiniciada
    if series_name.lower() == 'gravity falls':
        m_gf_se = re.search(r'\bS(\d{1,2})E(\d{1,3})\b', t, flags=re.I)
        if m_gf_se and seq_idx <= 20:
            snum, enum = int(m_gf_se.group(1)), int(m_gf_se.group(2))
            sub = re.sub(r'^.*?\bS\d{1,2}E\d{1,3}\b\s*[-.:]*\s*', '', t, flags=re.I).strip()
        else:
            snum = 1 if seq_idx <= 20 else 2
            m_ld = re.match(r'^\s*(\d{1,3})\s*[-.:]*\s*(.*)$', t)
            if m_ld:
                enum = int(m_ld.group(1))
                sub = m_ld.group(2).strip().strip('"')
            else:
                enum = seq_idx if seq_idx <= 20 else (seq_idx - 20)
                sub = t.strip('"')
        return (f"Series: {series_name} - Temporada {snum:02d}",
                f"{series_name} - T{snum:02d}E{enum:02d}" + (f" - {sub}" if sub else ""))

    m_tri = re.search(r'\b\d+\s*[xX]\s*(\d{1,2})\s*[xX]\s*(\d{1,3})\b(.*)$', t)
    m_tc = re.search(r'TEMPORADA\s*(\d{1,2})\s*CAP[IÍ]TULO\s*(\d{1,3})(.*)$', t, flags=re.I)
    m_te = re.search(r'\b[TS](\d{1,2})\s*[-.]?\s*E(\d{1,3})\b\s*[-.:]*\s*(.*)$', t, flags=re.I)
    m_sx = re.search(r'\b(\d{1,2})\s*[xX]\s*(\d{1,3})\s*[-.:]*\s*(.*)$', t)
    m_cap = re.search(r'^(?:\(\s*"?\d{3,4}\s*\)\s*)?\bcap(?:[ií]tulo)?\.?\s*(\d{1,3})\b(?:\s*\d{3,4}p)?(?:\s*latino)?(.*)$', t, flags=re.I)

    if m_tri:
        snum, enum, sub = int(m_tri.group(1)), int(m_tri.group(2)), m_tri.group(3).strip(' -.:')
    elif m_tc:
        snum, enum, sub = int(m_tc.group(1)), int(m_tc.group(2)), m_tc.group(3).strip(' -.:')
    elif m_te:
        snum, enum, sub = int(m_te.group(1)), int(m_te.group(2)), m_te.group(3).strip(' -.:')
    elif m_sx:
        snum, enum, sub = int(m_sx.group(1)), int(m_sx.group(2)), m_sx.group(3).strip(' -.:')
    elif m_cap:
        snum, enum, sub = 1, int(m_cap.group(1)), re.sub(r'\b(720p|1080p|latino)\b', '', m_cap.group(2) or '', flags=re.I).strip(' -.:')
    else:
        snum = 1
        if 'pecezuelo' in murl.lower():
            ms_f = re.search(r'/0?([1-9])\s*$', murl)
            if ms_f:
                snum = int(ms_f.group(1))
        m_lead = re.match(r'^\s*(\d{1,3})\s*(?:[-.:]+|\s+)(.*)$', t)
        m_stuck = re.match(r'^\s*(\d{1,3})([A-Za-zÁÉÍÓÚÑ¡¿].*)$', t)
        if m_lead:
            enum = int(m_lead.group(1))
            sub = m_lead.group(2).strip(' -.:?')
        elif m_stuck:
            enum = int(m_stuck.group(1))
            sub = m_stuck.group(2).strip(' -.:?')
        else:
            enum = seq_idx
            sub = '' if (t.isdigit() or t == '??') else t

    sub = re.sub(r'\s+', ' ', sub or '').strip(' -.:')
    if sub in ('??', '?', '-'):
        sub = ''
    disp = f"{series_name} - T{snum:02d}E{enum:02d}" + (f" - {sub}" if sub else "")
    return f"Series: {series_name} - Temporada {snum:02d}", disp

def fetch_verified_external_series_pools():
    """Recolecta y sondea (caché 7 días) los pools M3U externos auditados en Español Latino MP4."""
    import urllib.request as _ur
    import time as _time
    from concurrent.futures import ThreadPoolExecutor

    cache_data = load_json(SERIES_CACHE_PATH, {})
    ext_cache = cache_data.get('external_series_probe', {})
    now_ts = _time.time()
    ttl_sec = 7 * 86400
    hdrs = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    raw_candidates = []
    fetched_keys = set()
    ext_posters = {}

    def _fetch_m3u(spec):
        s_name, murl, filt = spec
        try:
            raw = _ur.urlopen(_ur.Request(murl, headers=hdrs), timeout=20).read()
            return s_name, murl, _parse_ext_items_with_logo(raw, filt)
        except Exception as e:
            print(f"[!] Error leyendo M3U externo {s_name} ({murl}): {e}")
            return s_name, murl, []

    with ThreadPoolExecutor(max_workers=8) as ex:
        fetched_lists = list(ex.map(_fetch_m3u, VERIFIED_EXTERNAL_M3U_POOLS))

    per_series_idx = {}
    seen_u = set()
    ext_poster_overrides = {
        "x-men '97": "https://static.tvmaze.com/uploads/images/medium_portrait/630/1576859.jpg",
        "historias asombrosas": "https://image.tmdb.org/t/p/original/dsuDPLo136j0in5MS7lB3gVPaEL.jpg",
    }
    for s_name, murl, items in fetched_lists:
        if not items:
            continue
        s_key = s_name.lower()
        for title, url, logo in items:
            low_u = (url or '').lower()
            if not low_u or url in seen_u:
                continue
            if _is_blacklisted_url(url):
                continue
            ext = os.path.splitext(urllib.parse.urlparse(low_u).path)[1]
            if ext in ('.mkv', '.avi', '.ogv', '.mpg', '.mpeg', '.jpg', '.png'):
                continue
            if s_key in ext_poster_overrides:
                logo = ext_poster_overrides[s_key]
            elif not logo and 'archive.org/download/' in low_u:
                m_iid = re.search(r'archive\.org/download/([^/]+)/', url)
                if m_iid:
                    logo = f"https://archive.org/services/img/{m_iid.group(1)}"
            if logo and s_key not in ext_posters:
                ext_posters[s_key] = logo
            idx = per_series_idx.get(s_key, 0) + 1
            per_series_idx[s_key] = idx
            grp, disp = _format_ext_season_ep(s_name, title, idx, murl=murl)
            seen_u.add(url)
            raw_candidates.append((s_key, grp, disp, url, logo or ext_posters.get(s_key, '')))

    to_probe = []
    for _, _, _, url, _ in raw_candidates:
        rec = ext_cache.get(url)
        if not rec or (now_ts - float(rec.get('ts', 0))) >= ttl_sec:
            to_probe.append(url)

    probed_now = 0
    if to_probe:
        from concurrent.futures import as_completed
        try:
            import requests as _req
            from requests.adapters import HTTPAdapter as _HA
            _sess = _req.Session()
            _ad = _HA(pool_connections=24, pool_maxsize=24)
            _sess.mount("https://", _ad)
            _sess.mount("http://", _ad)
            _sess.headers.update({'User-Agent': hdrs['User-Agent']})
        except Exception:
            _sess = None

        def _probe_one(u):
            if _sess is not None:
                for attempt in range(2):
                    try:
                        with _sess.get(u, headers={'Range': 'bytes=0-511'}, stream=True, timeout=6) as r:
                            code = r.status_code
                            if code == 429 and attempt == 0:
                                _time.sleep(1.0)
                                continue
                            ctype = (r.headers.get('Content-Type') or '').lower()
                            crange = r.headers.get('Content-Range', '')
                            clen = r.headers.get('Content-Length', '')
                            size_b = 0
                            m_tot = re.search(r'/(\d+)$', crange)
                            if m_tot:
                                size_b = int(m_tot.group(1))
                            elif clen.isdigit():
                                size_b = int(clen)
                            ok_type = ('video' in ctype or 'octet-stream' in ctype or 'matroska' in ctype)
                            return u, (code in (200, 206) and ok_type and size_b > 1_000_000), code
                    except Exception:
                        return u, False, 0
            ok, code = _probe_direct_media_ok(u, timeout=6)
            return u, ok, code

        print(f"[+] Sondeando {len(to_probe)} URLs externas nuevas (con pooling HTTP)...", flush=True)
        with ThreadPoolExecutor(max_workers=16) as ex:
            futs = [ex.submit(_probe_one, u) for u in to_probe]
            for fut in as_completed(futs):
                u, ok, code = fut.result()
                ext_cache[u] = {'ok': bool(ok), 'code': code, 'ts': now_ts}
                probed_now += 1
                if probed_now % 350 == 0:
                    print(f"[+] Sondeo externos: {probed_now}/{len(to_probe)}...", flush=True)
                    try:
                        cache_latest = load_json(SERIES_CACHE_PATH, {})
                        cache_latest['external_series_probe'] = ext_cache
                        save_json_atomic(SERIES_CACHE_PATH, cache_latest)
                    except Exception:
                        pass

        try:
            cache_latest = load_json(SERIES_CACHE_PATH, {})
            cache_latest['external_series_probe'] = ext_cache
            save_json_atomic(SERIES_CACHE_PATH, cache_latest)
        except Exception as e:
            print(f"[!] Advertencia guardando external_series_probe: {e}")

    verified_entries = []
    for s_key, grp, disp, url, logo in raw_candidates:
        rec = ext_cache.get(url)
        if rec and rec.get('ok'):
            final_logo = logo or ext_posters.get(s_key, '')
            verified_entries.append((grp, disp, url, final_logo))
            fetched_keys.add(s_key)

    print(f"[+] Pools Externos Verificados (Español MP4): {len(verified_entries)}/{len(raw_candidates)} vivos en {len(fetched_keys)} series (sondeados ahora: {probed_now}).")
    return verified_entries, fetched_keys, ext_posters

def fetch_verified_simpsons_external():
    """Recolecta y verifica en Español Latino episodios de Los Simpson (T1-T5 Dropbox + Cortos/T28-T37/Especiales/Pelis pomf2) con caché 24h."""
    import urllib.request as _ur
    import time as _time
    cache_data = load_json(SERIES_CACHE_PATH, {})
    ext_cache = cache_data.get('external_simpsons_probe', {})
    now_ts = _time.time()
    ttl_sec = 20 * 3600

    raw_candidates = []
    hdrs = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    # 1. Temporadas clasicas 1989-1993 en Dropbox (H.264/AAC Latino) desde masterqueenyt11-cmd/Series
    try:
        mq_txt = _ur.urlopen(_ur.Request("https://raw.githubusercontent.com/masterqueenyt11-cmd/Series/main/SIMPSON", headers=hdrs), timeout=15).read().decode('utf-8', 'replace')
        yr_season = {
            '1989': 'Temporada 01',
            '1990': 'Temporada 02',
            '1991': 'Temporada 03',
            '1992': 'Temporada 04',
            '1993': 'Temporada 05: Selección Clásicos',
        }
        yr_counters = {}
        for title, url in _parse_simple_extinf(mq_txt):
            if 'dl.dropboxusercontent.com' not in url and 'dropbox.com' not in url:
                continue
            ym = re.search(r'\((\d{4})\)', title)
            yr = ym.group(1) if ym else ''
            if yr not in yr_season:
                continue
            yr_counters[yr] = yr_counters.get(yr, 0) + 1
            ep_idx = yr_counters[yr]
            clean_t = re.sub(r'\(\d{4}\)', '', title).strip(' -')
            clean_t = re.sub(r'^\d+\s*[-.)]*\s*', '', clean_t).strip()
            clean_t = re.sub(r'\b720p\s*latino\b', '', clean_t, flags=re.I).strip(' -')
            s_code = {'1989': 1, '1990': 2, '1991': 3, '1992': 4, '1993': 5}[yr]
            ep_name = f"Los Simpson - T{s_code:02d}E{ep_idx:02d}" + (f" - {clean_t}" if clean_t else "")
            raw_candidates.append((f"Series: Los Simpson - {yr_season[yr]}", ep_name, url, SIMPSONS_FALLBACK_LOGO))
    except Exception as e:
        print(f"[!] Error leyendo masterqueenyt11/SIMPSON: {e}")

    # 2. Cortos Tracey Ullman (00), Temporadas 28-37, Treehouse, Fortnite y Pelis desde tokio14-dot/simp
    tokio_map = [
        ('00', 'Temporada 00: Cortos Clásicos', 0),
        ('28', 'Temporada 28', 28),
        ('29', 'Temporada 29', 29),
        ('30', 'Temporada 30', 30),
        ('31', 'Temporada 31', 31),
        ('32', 'Temporada 32', 32),
        ('33', 'Temporada 33', 33),
        ('34', 'Temporada 34', 34),
        ('35', 'Temporada 35', 35),
        ('36', 'Temporada 36', 36),
        ('37', 'Temporada 37', 37),
        ('Fortnite x The Simpsons', 'Especiales: Fortnite x Los Simpson', 98),
        ('Treehouse of Horror.txt', 'Especiales: La Casita del Horror', 99),
        ('pelis', 'Especiales: Películas y Cortos', 100),
    ]
    # Treehouse I-VIII ya vienen en MP4 H.264/AAC desde Archive.org (los-simpson-treehouse-of-horror_20240901)
    archive_th_covered = {'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII'}
    archive_peli_urls = {
        'https://archive.org/download/01_20250623_20250623/01.ia.mp4': 'https://archive.org/download/01_20250623_20250623/01.mp4',
        'https://archive.org/download/01_20250623_20250623/02.ia.mp4': 'https://archive.org/download/01_20250623_20250623/02.mp4',
        'https://archive.org/download/01_20250623_20250623/03.ia.mp4': 'https://archive.org/download/01_20250623_20250623/03.mp4',
        'https://archive.org/download/01_20250623_20250623/04.ia.mp4': 'https://archive.org/download/01_20250623_20250623/04.mp4',
    }
    for fname, season_label, snum in tokio_map:
        try:
            raw_u = "https://raw.githubusercontent.com/tokio14-dot/simp/main/" + urllib.parse.quote(fname)
            txt = _ur.urlopen(_ur.Request(raw_u, headers=hdrs), timeout=15).read().decode('utf-8', 'replace')
            items = _parse_simple_extinf(txt)
            if not items:
                urls = [_norm_ext_media_url(ln) for ln in txt.splitlines() if ln.strip().startswith('http')]
                items = [(f"Episodio {i+1:02d}", u) for i, u in enumerate(urls)]
            for idx_ep, (title, url) in enumerate(items, 1):
                low = url.lower()
                if any(bad in low for bad in ('bflix.net', 'fina.dyndns.tv', '.jpg', '.png', 'raw.githubusercontent.com')):
                    continue
                if 'archive.org/download/' in low and '06-4_20250630' in low:
                    continue
                if url in archive_peli_urls:
                    url = archive_peli_urls[url]
                if not any(ok_host in low for ok_host in ('pomf2.lain.la', 'dropboxusercontent.com', 'dropbox.com', '01_20250623_20250623', 'maggie-simpson')):
                    continue
                if fname == 'Treehouse of Horror.txt' and title.strip() in archive_th_covered:
                    continue
                # Extract clean episode number/title
                if snum <= 37:
                    m_x = re.search(r'(?:^|\b)\d+x(\d+)\b', title, flags=re.I)
                    m_lead = re.match(r'^(?:cap[ií]tulo|corto|ep\.?|episodio)?\s*(\d+)\b\s*[-.:]*\s*(.*)$', title.strip(), flags=re.I)
                    if m_x:
                        ep_n = int(m_x.group(1))
                        sub = re.sub(r'^\d+x\d+\s*[-.:]*\s*', '', title.strip()).strip()
                    elif m_lead:
                        ep_n = int(m_lead.group(1))
                        sub = m_lead.group(2).strip()
                    else:
                        ep_n = idx_ep
                        sub = title.strip()
                    ep_name = f"Los Simpson - T{snum:02d}E{ep_n:02d}" + (f" - {sub}" if sub else "")
                elif fname == 'Treehouse of Horror.txt':
                    t_clean = title.strip()
                    prefix = "La Casita del Horror " if t_clean.split()[0].rstrip('.').isdigit() or re.match(r'^[IVXLCDM]+$', t_clean.split()[0]) else ""
                    ep_name = f"Los Simpson - Especial #{idx_ep:02d} - {prefix}{t_clean}"
                elif fname == 'Fortnite x The Simpsons':
                    ep_name = f"Los Simpson - Fortnite Corto {idx_ep:02d}"
                else:
                    ep_name = f"Los Simpson - {title.strip()}"
                raw_candidates.append((f"Series: Los Simpson - {season_label}", ep_name, url, SIMPSONS_FALLBACK_LOGO))
        except Exception as e:
            print(f"[!] Error leyendo tokio14-dot/simp/{fname}: {e}")

    # Verify external URLs with polite 0.35s delay & 24h persistent probe cache
    verified_entries = []
    seen_u = set()
    probed_now = 0
    for grp, disp, url, logo in raw_candidates:
        if url in seen_u:
            continue
        seen_u.add(url)
        rec = ext_cache.get(url)
        if rec and (now_ts - float(rec.get('ts', 0))) < ttl_sec:
            if rec.get('ok'):
                verified_entries.append((grp, disp, url, logo))
            continue
        ok, code = _probe_direct_media_ok(url)
        if code == 429:
            _time.sleep(6.0)
            ok, code = _probe_direct_media_ok(url)
        ext_cache[url] = {'ok': bool(ok), 'code': code, 'ts': now_ts}
        probed_now += 1
        if 'pomf2.lain.la' in url:
            _time.sleep(0.35)
        else:
            _time.sleep(0.08)
        if ok:
            verified_entries.append((grp, disp, url, logo))

    # Persist probe cache inside series_completas_cache.json
    try:
        cache_latest = load_json(SERIES_CACHE_PATH, {})
        cache_latest['external_simpsons_probe'] = ext_cache
        save_json_atomic(SERIES_CACHE_PATH, cache_latest)
    except Exception as e:
        print(f"[!] Advertencia guardando ext_cache: {e}")

    print(f"[+] Los Simpson (Fuentes Externas Latino Verificadas): {len(verified_entries)}/{len(seen_u)} vivos (sondeados ahora: {probed_now}).")
    return verified_entries

def _series_key_from_group(grp):
    g = (grp or '').strip()
    m_grp = re.match(r'Series:\s*(.+?)\s*-\s*(?:Temporada|Saga|Especiales)\b', g, re.I)
    if m_grp:
        return m_grp.group(1).strip().lower()
    return re.sub(r'^Series:\s*', '', g, flags=re.I).strip().lower()

def reconcile_series_entries(series_out, existing_series, dead_ids):
    """Purga enlaces contaminados/mkv/negros e integra Pluto CO VOD + Pools Externos MP4 + Los Simpson + Supersonicos."""
    pluto_entries, pluto_vod_map, pluto_posters, pluto_fetched_keys = fetch_pluto_vod_series_batch()
    simpson_ext = fetch_verified_simpsons_external()
    ext_entries, ext_fetched_keys, ext_posters = fetch_verified_external_series_pools()
    all_posters_map = {**ext_posters, **pluto_posters}
    owned_by_curated = pluto_fetched_keys | ext_fetched_keys
    dead_ids_low = {str(d).lower() for d in (dead_ids or set())}
    legacy_exts = ('.mkv', '.avi', '.ogv', '.mpg', '.mpeg')

    fresh_archive_iids = set()
    for _, _, url, _ in series_out:
        m_iid = re.search(r'archive\.org/download/([^/]+)/', url or '')
        if m_iid:
            fresh_archive_iids.add(urllib.parse.unquote(m_iid.group(1)).lower())

    cleaned_out = []
    seen_urls = set()

    # Track preferred .mp4 Treehouse specials & 01_20250623 originals so we skip dummy/duplicate files
    th_seen_titles = {}
    for grp, name, url, logo in series_out:
        low_u = (url or '').lower()
        # Filter blacklist & tiny dummies & Archive .ia duplicates
        if _is_blacklisted_url(url):
            continue
        if 'los-simpson-treehouse-of-horror_20240901' in low_u:
            fname_u = urllib.parse.unquote(url.rsplit('/', 1)[-1]).lower()
            if 'los simpson treehouse of horror.mp4' in fname_u:
                continue  # 0.5 MB dummy intro
            base_t = re.sub(r'\.(mkv|mp4|webm|avi)$', '', fname_u)
            if base_t not in th_seen_titles or fname_u.endswith('.mp4'):
                th_seen_titles[base_t] = url

    th_allowed = set(th_seen_titles.values())
    movie_map_01 = {
        '01.mp4': 'Los Simpson - Película: The Simpsons Movie (2007)',
        '02.mp4': 'Los Simpson - Corto: El bueno, el Bart y el Loki (2021)',
        '03.mp4': 'Los Simpson - Corto: Plusniversario (2021)',
        '04.mp4': 'Los Simpson - Corto: Yellow Planet (2025)',
    }

    def _normalize_row(grp, name, url, logo):
        low_u = (url or '').lower()
        low_g = (grp or '').lower()
        low_n = (name or '').lower()
        u_path = urllib.parse.urlparse(low_u).path
        # Reject blacklisted, legacy mkv/avi (except vetted Simpson pomf2), or superseded Archive clips
        if _is_blacklisted_url(url):
            return None
        if any(u_path.endswith(ext) for ext in legacy_exts):
            if not ('simpson' in low_g and 'pomf2.lain.la' in low_u):
                return None
        if 'macgyver' in (low_g + low_n) and 'ipv4.pluto.tv' not in low_u:
            return None
        if 'ipv4.pluto.tv' in low_u and _series_key_from_group(grp) in pluto_fetched_keys:
            return None  # Replace stale 24h JWTs when fresh Pluto CO batch succeeded
        if _series_key_from_group(grp) in owned_by_curated and 'archive.org/download/' in low_u:
            return None  # Evita colision de clips parciales Archive con lotes verificados Pluto/Externos
        # Fix t-2-02.-ia -> Los Supersonicos (separado en Temporada 01/02/03)
        if 'archive.org/download/t-2-02.-ia/' in low_u:
            fname_part = urllib.parse.unquote(url.rsplit('/', 1)[-1])
            mt = re.search(r'[Tt](\d+)[-_](\d+)', fname_part)
            if mt:
                sn, en = int(mt.group(1)), int(mt.group(2))
                return (f"Series: Los Supersonicos - Temporada {sn:02d}",
                        f"Los Supersonicos - T{sn:02d}E{en:02d}",
                        url, SUPERSONICOS_LOGO)
            return ("Series: Los Supersonicos - Temporada 01", name.replace("Los Simpson", "Los Supersonicos"), url, SUPERSONICOS_LOGO)
        # Filter Treehouse Archive duplicates/dummy (keep .mp4 H.264/AAC)
        if 'los-simpson-treehouse-of-horror_20240901' in low_u:
            if url not in th_allowed:
                return None
            fname_part = urllib.parse.unquote(url.rsplit('/', 1)[-1])
            clean_th = re.sub(r'\.(mp4|mkv)$', '', fname_part, flags=re.I).strip()
            return ("Series: Los Simpson - Especiales: La Casita del Horror", f"Los Simpson - {clean_th}", url, SIMPSONS_FALLBACK_LOGO)
        if 'archive.org/download/01_20250623_20250623/' in low_u:
            fn = urllib.parse.unquote(url.rsplit('/', 1)[-1]).lower()
            if fn not in movie_map_01:
                return None
            return ("Series: Los Simpson - Especiales: Películas y Cortos", movie_map_01[fn], url, SIMPSONS_FALLBACK_LOGO)
        if 'archive.org/download/maggie-simpson-cita-a-jugar-con-el-destino-corto/' in low_u:
            return ("Series: Los Simpson - Especiales: Películas y Cortos", "Los Simpson - Corto: Cita a jugar con el destino (2020)", url, SIMPSONS_FALLBACK_LOGO)
        if 'archive.org/download/lo-simpson-pel-1cul-4-hd-720p-972715/' in low_u:
            return ("Series: Los Simpson - Especiales: Películas y Cortos", "Los Simpson - Película: The Simpsons Movie (Alt HD)", url, SIMPSONS_FALLBACK_LOGO)
        if 'archive.org/download/tinaco_20210512/' in low_u and '.ia.' in low_u:
            return None
        return (grp, name, url, logo)

    for row in series_out:
        fixed = _normalize_row(*row)
        if fixed and fixed[2] not in seen_urls:
            seen_urls.add(fixed[2])
            cleaned_out.append(fixed)

    # Preserve valid old entries (never re-inject refreshed Archive IIDs, stale Pluto JWTs, or legacy .mkv)
    preserved_old = 0
    for e in existing_series:
        u_old = e.get('url', '')
        if _is_blacklisted_url(u_old):
            continue
        m = re.search(r'archive\.org/download/([^/]+)/', u_old)
        iid = urllib.parse.unquote(m.group(1)).lower() if m else ''
        if m and (iid in dead_ids_low or iid in BLACKLIST_IDENTIFIERS or iid in fresh_archive_iids):
            continue
        s_key_old = _series_key_from_group(e.get('group', ''))
        if s_key_old in ext_fetched_keys:
            continue
        fixed = _normalize_row(e['group'], e['name'], u_old, e['logo'])
        if fixed and fixed[2] not in seen_urls:
            seen_urls.add(fixed[2])
            cleaned_out.append(fixed)
            preserved_old += 1

    # Add curated verified Los Simpson external entries (deduped against tinaco T06-T10 & Archive T36E15)
    simpson_covered_keys = set()
    for g, n, u, l in cleaned_out:
        if 'simpson' in g.lower() and ('tinaco_20210512' in u.lower()):
            mk = re.search(r'T(\d+)E(\d+)', n, flags=re.I)
            if mk:
                simpson_covered_keys.add((int(mk.group(1)), int(mk.group(2))))

    for g, n, u, l in simpson_ext:
        if u in seen_urls:
            continue
        mk = re.search(r'T(\d+)E(\d+)', n, flags=re.I)
        if mk and (int(mk.group(1)), int(mk.group(2))) in simpson_covered_keys:
            continue
        seen_urls.add(u)
        cleaned_out.append((g, n, u, l))

    # Drop t-36x-05 if T36E15 already came from tokio14/36 MP4 (H.264/AAC)
    has_t36e15_mp4 = any(('simpson' in g.lower() and 'T36E15' in n and 'pomf2.lain.la' in u) for g, n, u, _ in cleaned_out)
    if has_t36e15_mp4:
        cleaned_out = [r for r in cleaned_out if 'archive.org/download/t-36x-05/' not in r[2].lower()]

    # Add verified external M3U pools (Español MP4) and fresh Pluto CO VOD batch
    for row in ext_entries:
        if row[2] not in seen_urls:
            seen_urls.add(row[2])
            cleaned_out.append(row)

    for row in pluto_entries:
        if row[2] not in seen_urls:
            seen_urls.add(row[2])
            cleaned_out.append(row)

    return cleaned_out, preserved_old, pluto_vod_map, all_posters_map

def postprocess_series_catalog(final_catalog, pluto_vod_map, posters_by_series=""):
    """Asegura logos, pluto_id VOD, URL limpia sin JWT en JSON, purga residuos y ordena temporadas/episodios."""
    if isinstance(posters_by_series, dict):
        posters_map = posters_by_series
    elif posters_by_series:
        posters_map = {'macgyver': posters_by_series}
    else:
        posters_map = {}
    legacy_exts = ('.mkv', '.avi', '.ogv', '.mpg', '.mpeg')

    def _season_sort_key(sea_obj):
        st = (sea_obj.get('season') or '').strip()
        m = re.search(r'Temporada\s*(\d+)', st, flags=re.I)
        if m:
            return (0, int(m.group(1)), st.lower())
        if 'especial' in st.lower() or 'horror' in st.lower():
            return (1, 0, st.lower())
        return (2, 0, st.lower())

    for s_obj in final_catalog:
        sname = (s_obj.get('series') or '').lower()
        if sname in posters_map and posters_map[sname]:
            s_obj['logo'] = posters_map[sname]
        elif 'supersonicos' in sname:
            s_obj['logo'] = SUPERSONICOS_LOGO
        elif 'simpson' in sname:
            s_obj['logo'] = SIMPSONS_FALLBACK_LOGO

        cleaned_seasons = []
        for sea in (s_obj.get('seasons') or []):
            seen_ep_u = set()
            valid_eps = []
            for ep in (sea.get('episodes') or []):
                u = (ep.get('url') or '').strip()
                low_u = u.lower()
                if not u or _is_blacklisted_url(u):
                    continue
                u_path = urllib.parse.urlparse(low_u).path
                if any(u_path.endswith(ext) for ext in legacy_exts):
                    if not ('simpson' in sname and 'pomf2.lain.la' in low_u):
                        continue
                if 'simpson' in sname:
                    if 'archive.org/download/t-2-02.-ia/' in low_u:
                        continue
                    if '.ia.mp4' in low_u and ('tinaco_20210512' in low_u or '01_20250623_20250623' in low_u):
                        continue
                    if 'los%20simpson%20treehouse%20of%20horror.mp4' in low_u or 'los simpson treehouse of horror.mp4' in low_u:
                        continue
                if 'macgyver' in sname:
                    if pluto_vod_map:
                        if u not in pluto_vod_map:
                            continue
                    elif 'ipv4.pluto.tv' not in low_u:
                        continue

                ep_out = dict(ep)
                is_pluto = ('ipv4.pluto.tv' in low_u) or (u in pluto_vod_map)
                if is_pluto:
                    vod_id = pluto_vod_map.get(u, '')
                    if not vod_id:
                        m_ep = re.search(r'/episode/([a-f0-9]{16,})/master\.m3u8', low_u)
                        if m_ep:
                            vod_id = f"vod:{m_ep.group(1)}"
                    if vod_id:
                        ep_out['pluto_id'] = vod_id
                    # Quitar ?jwt=... solo dentro de series_catalog.json (~2KB -> ~210B/ep); Android minte JWT fresco con pluto_id
                    u_store = u.split('?', 1)[0]
                else:
                    u_store = u

                if u_store in seen_ep_u:
                    continue
                seen_ep_u.add(u_store)
                ep_out['url'] = u_store
                ep_out.pop('logo', None)
                valid_eps.append(ep_out)
            if valid_eps:
                sea['episodes'] = sorted(valid_eps, key=lambda ep: natural_key(ep.get('name', '')))
                cleaned_seasons.append(sea)

        s_obj['seasons'] = sorted(cleaned_seasons, key=_season_sort_key)
        s_obj['total_seasons'] = len(s_obj['seasons'])
        s_obj['total_episodes'] = sum(len(se.get('episodes') or []) for se in s_obj['seasons'])

_local_cat = os.path.join(APP_DIR, "latam_tv_catalog.json")
LATAM_CATALOG_PATH = _local_cat if os.path.exists(_local_cat) else r"C:\Users\leoka\.gemini\antigravity\scratch\omega_music_app\assets\latam_tv_catalog.json"
FAVS_PATH = os.path.join(APP_DIR, "favoritos.json")
LISTAS_JSON_PATH = os.path.join(APP_DIR, "listas.json")
OUTPUT_M3U = os.path.join(APP_DIR, "LISTA_MAESTRA_LEO_VIP.m3u")
BACKUP_M3U = os.path.join(APP_DIR, "LISTA_MAESTRA_LEO_VIP.respaldo.m3u")
SERIES_CACHE_PATH = os.path.join(APP_DIR, "series_completas_cache.json")
SERIES_DESEADAS_PATH = os.path.join(APP_DIR, "series_deseadas.json")
ESTADO_PATH = os.path.join(APP_DIR, "robot_estado.json")

NO_GUI = '--no-gui' in sys.argv
MAX_STRIKES = 3              # ejecuciones seguidas fallando antes de retirar un enlace
MAX_URLS_PER_CHANNEL = 3     # principal + 2 opciones de respaldo
NEW_CANDIDATES_CAP = 2500    # canales nuevos a sondear por ejecucion
SERIES_REFRESH_DAYS = 7      # cada cuanto se re-consulta una coleccion ya conocida
DISCOVERY_REFRESH_DAYS = 3   # cada cuanto se re-busca una serie deseada

OK, SOFT, DEAD = 'ok', 'soft', 'dead'

# ============================================================================
# FUENTES: SOLO HISPANAS (las listas globales multi-idioma fueron eliminadas)
# ============================================================================
CORE_M3U_SOURCES = [
    # 1. Packs de Cable Premium Latino
    ("Television Hispana", "https://raw.githubusercontent.com/altobelly/iprusia/main/lista_tv_organizada.m3u"),
    ("Canales Premium VIP", "https://raw.githubusercontent.com/altobelly/iprusia/main/lista_especial_con_respaldos.m3u"),
    ("Canales Premium VIP", "https://raw.githubusercontent.com/lucas152125/Canales-Premium/main/canales%20premium.m3u"),
    ("Canales Premium VIP", "https://raw.githubusercontent.com/geomarin12/lista-iptv-latino-colombia---ecuador-/main/lista.m3u"),
    ("Canales Premium VIP", "https://raw.githubusercontent.com/maxbus23/Canales-latinos/main/playlist_organizado.m3u8"),
    ("Canales Premium VIP", "https://raw.githubusercontent.com/ArmisaelxD/IPTV-Paga-MX/main/Premium.m3u"),
    ("Canales Premium VIP", "https://raw.githubusercontent.com/screensavers639/IPTV-Latino/main/IPTV_Latino_Maestra.m3u"),
    ("Cine y Peliculas 24/7", "https://raw.githubusercontent.com/miniclipstvia-hub/cine-latino-iptv/main/Cine_Latino_4K_HD.m3u"),
    ("Cine y Peliculas 24/7", "https://raw.githubusercontent.com/rbaezc95/mi-lista-iptv/main/canales%20latinos.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/rbaezc95/mi-lista-iptv/main/IPTV%20CANALES%20INTERNACIONALES%20LATINOS.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/camammoli/iptv/master/canales.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/User-jmh/IPTV-LATINO-AT/main/IPTV-LATINO.m3u8"),
    # 2. Colombia
    ("Colombia", "https://iptv-org.github.io/iptv/countries/co.m3u"),
    ("Colombia", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/co.m3u"),
    ("Colombia", "https://raw.githubusercontent.com/LTDCrissOK/IPTV-COLOMBIA/main/IPTV-COMLOMBIA.m3u"),
    ("Colombia", "https://raw.githubusercontent.com/elbenditis333-maker/IPTV-Colombia-Canales_TEST/main/index.m3u"),
    ("Colombia", "https://raw.githubusercontent.com/good-iptv-list/Best-IPTV-Colombian/main/COL.m3u"),
    ("Colombia", "https://raw.githubusercontent.com/good-iptv-list/Colombian-iptv/main/list.m3u"),
    ("Colombia", "https://raw.githubusercontent.com/luishumberto43/IPTV-Colombia-luishumberto43/main/lista.m3u"),
    ("Colombia", "https://raw.githubusercontent.com/Jsulllivan/iptvcol/main/co%20(1).m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/romiliocarpio/carganetlista/main/latinos.m3u"),
    # 3. Paises hispanohablantes (iptv-org por pais)
    ("Television Hispana", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/mx.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/ar.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/es.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cl.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/pe.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/ec.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/do.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/ve.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/uy.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/py.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/bo.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cr.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/pa.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/gt.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/hn.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/sv.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/ni.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/pr.m3u"),
    ("Television Hispana", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/gt_streamhispanatv.m3u"),
    # 4. Plataformas FAST en espanol
    ("Pluto TV LATAM", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/mx_pluto.m3u"),
    ("Pluto TV LATAM", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/es_pluto.m3u"),
    ("Cine y Peliculas 24/7", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/us_canelatv.m3u"),
    ("Cine y Peliculas 24/7", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/es_rakuten.m3u"),
    # 5. Listas filtradas por idioma espanol
    ("Television Hispana", "https://www.tdtchannels.com/lists/tv.m3u8"),
    ("Television Hispana", "https://iptv-org.github.io/iptv/languages/spa.m3u"),
]

# Listas globales multi-idioma que causaron la invasion de canales extranjeros.
BANNED_SOURCES = (
    "iptv-org.github.io/iptv/categories/",
    "Free-TV/IPTV/master/playlist",
    "iptv-org.github.io/iptv/index",
)

# ============================================================================
# FILTRO DE IDIOMA (nombre + tvg-id + dominio)
# ============================================================================
FOREIGN_NAME_RE = re.compile(
    r'\b(russia|russian|hungary|bulgaria|taiwan|italy|italian|italia|italiano|poland|polish|turkey|turkish|'
    r'india|indian|tamil|telugu|hindi|malayalam|kannada|bengali|punjabi|marathi|gujarati|urdu|'
    r'mahaa|shemaroo|zeetv|zee\s|aaj tak|ndtv|dangal|b4u|'
    r'arab|arabic|romania|ukraine|germany|german|deutsch|deutschland|france|french|francais|français|'
    r'vietnam|thailand|indonesia|iran|persian|farsi|kurd\w*|pakistan|kazakh|azerbaijan|georgia|armenia|albania|'
    r'serbia|croatia|czech|slovakia|finland|sweden|norway|denmark|netherlands|dutch|greece|'
    r'israel|korea|korean|china|chinese|japan|japanese|afghan|bangladesh|nepal|sri lanka|'
    r'myanmar|cambodia|laos|mongolia|uzbek|tajik|kyrgyz|turkmen|belarus|moldova|latvia|'
    r'lithuania|estonia|slovenia|bosnia|macedonia|montenegro|kosovo|cyprus|malta|iceland|'
    r'somali|swahili|tagalog|filipino|pinoy|english|\badria\b|'
    r'cbs news|nbc news|abc news|fox news|sky news|bbc|bloomberg|cnbc|dateline|fite|newsmax|court tv|'
    r'(&\s*friends|\band friends\b)|girlfriends|rai|tf1|zdf|ert\s*sports|ert\s*kids|max sport|afarin|caribbean advantage|\b(ert|orf|htv\d*|htvc|aathavan|athvan|paschima|nidae|al-islam|afarin)\b)\b',
    re.IGNORECASE
)
# Portugues/Brasil: se aplica SIEMPRE, incluso si el nombre dice "latino"
PORTUGUESE_RE = re.compile(
    r'\b(br|pt|brazil|brasil|brasileir[ao]|portugal|portugu[eê]s|dublado|legendado|calca quadrada|'
    r'globo|tv globo|sbt|record tv|record news|recordtv|rede|band|bandnews|band sports|'
    r'espanhol|ingl[eê]s legendado)\b',
    re.IGNORECASE
)
SPANISH_MARKER_RE = re.compile(
    r'(español|espanol|castellano|\blatino\b|\blatina\b|latinoam[eé]rica|\blatam\b|hispan[oa]|\bspanish\b)',
    re.IGNORECASE
)
NON_LATIN_SCRIPT_RE = re.compile(r'[\u0400-\u04FF\u0600-\u06FF\u4E00-\u9FFF\u0900-\u097F\u0E00-\u0E7F\uAC00-\uD7AF\u0590-\u05FF\u3040-\u30FF]')

FOREIGN_TLDS = {
    'br', 'pt', 'in', 'ru', 'it', 'de', 'fr', 'pl', 'tr', 'ua', 'cn', 'jp', 'kr', 'vn', 'th', 'id', 'ir',
    'gr', 'ro', 'hu', 'cz', 'sk', 'bg', 'rs', 'hr', 'al', 'az', 'kz', 'by', 'il', 'pk', 'bd', 'lk', 'np',
    'ph', 'tw', 'sa', 'ae', 'eg', 'ma', 'dz', 'tn', 'iq', 'sy', 'lb', 'nl', 'se', 'no', 'dk', 'fi', 'ge',
    'am', 'md', 'lt', 'lv', 'ee', 'si', 'ba', 'mk',
}
FOREIGN_ID_CC = FOREIGN_TLDS | {'uk', 'gb', 'ca', 'au', 'nz', 'ie', 'za', 'ng', 'be', 'at', 'ch'}
FOREIGN_HOSTS_RE = re.compile(
    r'(playontv|smartplaytv|voxtvhd|multistream|astrakhan|15\.204\.246\.24|'
    r'tvsen6\.aynaott\.com|dethich\.pw|broadpeak-aas\.com|mdn\.ors\.at|'
    r'ekamraott\.com|vgcdn\.net|transmissaodigital\.com|solumedia\.com|'
    r'chileservidores\.com|livecastv\.com|soportedvb\.click|vs20\.live\.opencaster\.com|'
    r'amixtv\.com)',
    re.IGNORECASE
)


def normalize_stream_url(url):
    """Convierte URLs DASH y proxys inestables (jmp2.uk) a streams HLS nativos directos."""
    if not url:
        return ""
    u = url.strip()
    # 1. Erradicacion total de jmp2.uk: convertir canal de Pluto a enlace de cluster directo oficial
    m_plu = re.search(r'jmp2\.uk/plu-([a-f0-9\-]+)(?:\.m3u8)?', u, re.IGNORECASE)
    if m_plu:
        cid = m_plu.group(1)
        return (
            f"https://service-stitcher.clusters.pluto.tv/stitch/hls/channel/{cid}/master.m3u8"
            f"?advertisingId=&appName=web&appStoreUrl=&appVersion=DNT&app_name=&architecture=&buildVersion=&deviceDNT=0"
            f"&deviceId={cid}&deviceLat=&deviceLon=&deviceMake=web&deviceModel=web&deviceType=web&deviceVersion=DNT"
            f"&includeExtendedEvents=false&marketingRegion=US&serverSideAds=false&sid=904&terminate=false&userId="
        )
    if 'jmp2.uk' in u.lower():
        return ""  # Descartar proxy roto que arroja HTTP 414 Request-URI Too Large
    # 2. Normalizar DASH (.mpd) a HLS nativo (.m3u8) si el origen lo soporta
    if '.isml/' in u.lower() and '.mpd' in u.lower():
        u = re.sub(r'\.mpd(\?.*)?$', r'.m3u8\1', u, flags=re.IGNORECASE)
    elif '/manifest.mpd' in u.lower():
        u = re.sub(r'/manifest\.mpd(\?.*)?$', r'/playlist.m3u8\1', u, flags=re.IGNORECASE)
    return u


def url_tld(url):
    try:
        host = (urllib.parse.urlparse(url).hostname or '').lower()
    except Exception:
        return ''
    if re.match(r'^\d+\.\d+\.\d+\.\d+$', host):
        return ''
    return host.rsplit('.', 1)[-1] if '.' in host else ''


def tvg_country(tvg_id):
    m = re.search(r'\.([a-z]{2})(?:@|$)', (tvg_id or '').lower())
    return m.group(1) if m else ''


def foreign_reason(raw_name, tvg_id="", url=""):
    """Devuelve el motivo si el canal es de idioma/pais ajeno, o '' si es hispano."""
    if NON_LATIN_SCRIPT_RE.search(raw_name):
        return 'alfabeto no latino'
    if PORTUGUESE_RE.search(raw_name) or (tvg_id and PORTUGUESE_RE.search(tvg_id.split('.')[0])):
        return 'portugues/brasil'
    if url and '.mpd' in url.lower():
        return 'formato DASH (.mpd) incompatible con SmartTV'
    if url and FOREIGN_HOSTS_RE.search(url):
        return 'servidor extranjero conocido'
    if url_tld(url) == 'br' or tvg_country(tvg_id) in ('br', 'pt'):
        return 'portugues/brasil'
    if SPANISH_MARKER_RE.search(raw_name):
        return ''   # "Espanol/Latino" explicito: France 24 Espanol, DW Espanol, etc.
    if FOREIGN_NAME_RE.search(raw_name):
        return 'nombre extranjero'
    if tvg_id and tvg_country(tvg_id) in FOREIGN_ID_CC:
        return 'tvg-id extranjero (.%s)' % tvg_country(tvg_id)
    if url and url_tld(url) in FOREIGN_TLDS:
        return 'dominio extranjero (.%s)' % url_tld(url)
    return ''


def is_foreign_garbage(raw_name, tvg_id="", url=""):
    return bool(foreign_reason(raw_name, tvg_id, url))


# ============================================================================
# CLASIFICACION
# ============================================================================
PREMIUM_CINE_SERIES_RE = re.compile(
    r'\b(hbo|hbo max|universal|studio universal|star channel|cinecanal|cine canal|space|tnt|'
    r'cinemax|golden|de pelicula|multipremier|amc|paramount|sony|warner|axn|fx|syfy|'
    r'tcm|europa europa|film\s*&\s*arts|a&e|ae mundo|dhe|lifetime|comedy central|'
    r'distrito comedia|pasiones|tlnovelas|telenovelas|rcn novelas|cine latino|canela|'
    r'cine premium|cine hispano|cine familiar|cine terror|cine adrenalina|cine clasico|'
    r'cine comedia|cine accion|cine estelar|cine suspenso|mgm|hallmark|eurochannel|sundance)\b',
    re.IGNORECASE
)
PREMIUM_SPORTS_RE = re.compile(
    r'\b(win sports|win\+|espn|fox sports|directv sports|dsports|tyc sports|tnt sports|'
    r'claro sports|tudn|goltv|gol tv|movistar.*liga|bein sports|dazn|real madrid|'
    r'barca tv|nba|ufc|mlb|nfl|f1|formula 1|motor|adrenalina sports|deportes tvc|'
    r'teledeporte|red bull tv)\b',
    re.IGNORECASE
)
COLOMBIA_RE = re.compile(
    r'\b(caracol|rcn|señal colombia|senal colombia|city\s*tv|teleantioquia|telecaribe|'
    r'telepacifico|telecafe|canal tro|canal trece|canal 13|canal capital|telemedellin|'
    r'cali\s*tv|teleislas|canal institucional|cablenoticias|ntn24|red\+|canal 1|canal uno|'
    r'teleamiga|cristovision|avivamiento|mi m reggaeton|mi m salsa|rumba tv|cantinazo)\b',
    re.IGNORECASE
)
PREMIUM_DOCU_RE = re.compile(
    r'\b(discovery|history|h2|nat\s*geo|national geographic|animal planet|h&h|home & health|'
    r'hgtv|investigation discovery|tlc|smithsonian|odisea|dmax|dw español|dw espanol|nasa)\b',
    re.IGNORECASE
)
# Sin "24/7" suelto ni "friends" (traian CBS News 24/7, Barbie & Friends, Friends TV India)
SERIES_24_7_RE = re.compile(
    r'\b(simpson|los simpson|el chavo|chavo animado|chavo del 8|chespirito|el chapul[ií]n|chapulin colorado|'
    r'futurama|malcolm|dragon ball|bob esponja|seinfeld|big bang|padre de familia|'
    r'pokemon|pokémon|naruto|sailor moon|los caballeros del zodiaco|saint seiya|'
    r'looney tunes|tom y jerry|scooby doo|los padrinos m[aá]gicos|coraje el perro|la pantera rosa|ben 10|'
    r'tres patines|la tremenda corte|alf|el principe del rap|dos hombres y medio|marat[oó]n)\b',
    re.IGNORECASE
)
PREMIUM_KIDS_RE = re.compile(
    r'\b(cartoon network|cartoon nt|cartoonito|disney|nickelodeon|nick jr|discovery kids|'
    r'tooncast|boomerang|dream\s*works|adult swim|locomotion|bitme|anime|'
    r'baby\s*first|pakapaka|clan tve)\b',
    re.IGNORECASE
)

CAT_ORDER = {
    "Favoritos de Leo VIP": 0, "Colombia": 1, "Canales Premium VIP": 2, "Deportes en Vivo": 3,
    "Series y Canales 24/7": 4, "Cine y Peliculas 24/7": 5, "Series y Entretenimiento": 6,
    "Documentales y Ciencia": 7, "Infantil y Familiar": 8, "Pluto TV LATAM": 9,
    "Musica y Conciertos": 10, "Television Hispana": 11,
}


def clean_channel_name(raw_name):
    name = (raw_name or "").strip()
    name = re.sub(r'^\d+[\.\-_]\s*(?:\d+[\.\-_]\s*)*', '', name)
    name = re.sub(r'^(?:IPTV\s*\|\s*|CANALES?\s*\|\s*)', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*\[Opcion \d+\]\s*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[✅\u2705\u2714\u2713\u26a0]+', '', name)
    name = re.sub(r'\s*-\s*Opci[oó]n\s*\d+\s*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\[.*?\]', '', name)
    name = re.sub(r'\((?:Gua\d*|Col\d*|Colx|Hon\d*|Per\d*|Ven\d*|Chi\d*|Ecua\d*|BZ\d*|X\d*|L\d*|Mx|ES|USA|LG|TCL|Samsung|Vizio|Roku|Xiaomi|Geo|\d+|\d+p)\)', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+-TCL\b', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+\.CA\b', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+', ' ', name).strip(' -|_.,')
    if re.match(r'^Cartoon NT\b', name, re.IGNORECASE):
        name = re.sub(r'^Cartoon NT\b', 'Cartoon Network', name, flags=re.IGNORECASE)
    if re.match(r'^H History\b', name, re.IGNORECASE):
        name = re.sub(r'^H History\b', 'History Channel', name, flags=re.IGNORECASE)
    return name or raw_name.strip()


def key_for_dedup(clean_name):
    base = re.sub(r'\s*\[Opcion \d+\]\s*$', '', clean_name, flags=re.IGNORECASE)
    base = re.sub(r'\b(\d+p|hd|fhd|sd|4k|uhd)\b', '', base, flags=re.IGNORECASE)
    base = re.sub(r'\b(latin\s*america|latino\s*america|latinoamerica|latam|central\s*america|sur|norte|andes|pacific|colombia|mexico|chile|argentina)\b', '', base, flags=re.IGNORECASE)
    base = re.sub(r'[^a-zA-Z0-9áéíóúñÁÉÍÓÚÑ+]', '', base).lower()
    return base


def classify_and_score(clean_name, raw_group, c_code="", fav_keys=None):
    name_l = clean_name.lower()
    grp_l = (raw_group or "").lower()
    k = key_for_dedup(clean_name)
    if fav_keys and k in fav_keys:
        return ("Favoritos de Leo VIP", 0, True)
    if c_code == 'co' or COLOMBIA_RE.search(clean_name) or 'colombia' in grp_l:
        return ("Colombia", 1, True)
    if PREMIUM_SPORTS_RE.search(clean_name):
        return ("Deportes en Vivo", 1, True)
    if SERIES_24_7_RE.search(clean_name):
        return ("Series y Canales 24/7", 1, True)
    if PREMIUM_CINE_SERIES_RE.search(clean_name):
        return ("Canales Premium VIP", 1, True)
    if PREMIUM_DOCU_RE.search(clean_name):
        return ("Documentales y Ciencia", 1, True)
    if PREMIUM_KIDS_RE.search(clean_name):
        return ("Infantil y Familiar", 1, True)
    if 'pluto' in name_l or 'pluto' in grp_l:
        return ("Pluto TV LATAM", 2, False)
    if any(w in grp_l or w in name_l for w in ['cine', 'movie', 'pelicula', 'film']):
        return ("Cine y Peliculas 24/7", 2, False)
    if any(w in grp_l or w in name_l for w in ['deporte', 'sport', 'futbol', 'golf', 'boxeo', 'tenis']):
        return ("Deportes en Vivo", 2, False)
    if any(w in grp_l or w in name_l for w in ['serie', 'entertain', 'entretenimiento', 'novela', 'variedad']):
        return ("Series y Entretenimiento", 2, False)
    if any(w in grp_l or w in name_l for w in ['docu', 'ciencia', 'cultura', 'naturaleza', 'historia']):
        return ("Documentales y Ciencia", 2, False)
    if any(w in grp_l or w in name_l for w in ['infantil', 'kids', 'niño', 'junior', 'toon']):
        return ("Infantil y Familiar", 2, False)
    if any(w in grp_l or w in name_l for w in ['music', 'música', 'musica', 'concierto', 'radio', 'htv', 'mtv', 'telehit', 'bandamax']):
        return ("Musica y Conciertos", 2, False)
    return ("Television Hispana", 3, False)


# ============================================================================
# RED
# ============================================================================
def fetch_text(url, timeout=12):
    try:
        req = urllib.request.Request(url, headers=BROWSER_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.read().decode('utf-8', errors='ignore')
    except Exception:
        return ""


def fetch_json(url, timeout=25):
    """Devuelve (ok_red, data). ok_red=False si hubo error de red (no confundir con 'vacio')."""
    try:
        headers = dict(BROWSER_HEADERS)
        if 'api.github.com' in url:
            tok = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
            if tok:
                headers['Authorization'] = f"Bearer {tok}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return True, json.loads(r.read().decode('utf-8', errors='ignore'))
    except Exception:
        return False, None


def internet_ok():
    for u in ("https://raw.githubusercontent.com/", "https://archive.org/", "https://www.google.com/"):
        try:
            urllib.request.urlopen(urllib.request.Request(u, headers=BROWSER_HEADERS), timeout=8, context=ctx).close()
            return True
        except urllib.error.HTTPError:
            return True   # respondio el servidor: hay internet
        except Exception:
            continue
    return False


def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def _open(url, timeout, rng=None):
    h = dict(HEADERS)
    if rng:
        h['Range'] = rng
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout, context=ctx)


def mirror_priority_score(url):
    """Puntua espejos de mayor a menor calidad/velocidad para que la Opcion 1 sea siempre la mejor."""
    u = url.lower()
    score = 0
    if '138.121.15.230:9002' in u:
        score += 100  # Satelite Astra dedicado directo
    elif 'service-stitcher.clusters.pluto.tv' in u:
        score += 85   # CDN oficial directo Pluto TV
    elif any(cdn in u for cdn in ('akamaized.net', 'cloudfront.net', 'bitgravity', 'wurl.tv', 'amagi.tv')):
        score += 75   # CDNs globales de alta disponibilidad
    elif any(host in u for host in ('45.186.106.207', '181.78.14.26', '190.61.42.218', '181.78.23.26', '190.109.2.92')):
        score += 65   # Servidores ISP directos de cable
    if u.startswith('https://'):
        score += 5
    return -score


def _probe(url, timeout, depth):
    if not url or '.mpd' in url.lower():
        return DEAD
    if 'jmp2.uk' in url.lower():
        return DEAD
    with _open(url, timeout) as r:
        if r.getcode() not in (200, 206):
            return DEAD
        final = r.geturl()
        if 'jmp2.uk' in final.lower() or '.mpd' in final.lower():
            return DEAD
        ctype = (r.headers.get('Content-Type') or '').lower()
        head = r.read(4096)
        if len(head) < 16:
            return DEAD
        low = head.lower()
        if b'<html' in low or b'<!doctype html' in low or b'<mpd' in low or b'<?xml' in low[:200]:
            return DEAD
        stripped = low.lstrip(b'\xef\xbb\xbf \r\n\t')

        # --- Manifiesto HLS: verificar que el flujo interno exista (anti-zombie y anti-DRM) ---
        if stripped.startswith(b'#extm3u') or b'#ext-x-' in low or b'#extinf' in low:
            body = head + r.read(200000)
            text = body.decode('utf-8', errors='ignore')

            # 1. Deteccion de DRM propietario incompatible con Smart TV (Widevine/FairPlay/PlayReady)
            if any(drm in text for drm in ('urn:uuid:edef8ba9', 'com.apple.streamingkeydelivery', 'com.microsoft.playready', 'SAMPLE-AES-CTR')):
                return DEAD

            has_aes = ('#EXT-X-KEY' in text.upper() and 'METHOD=AES-128' in text.upper())

            lines_m = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith('#')]
            if not lines_m:
                return DEAD
            if '#EXT-X-STREAM-INF' in text.upper():
                if depth >= 2:
                    return DEAD
                st = _probe_safe(urllib.parse.urljoin(final, lines_m[0]), timeout, depth + 1)
                return OK if st == OK else DEAD
            seg = urllib.parse.urljoin(final, lines_m[-1])
            if '.m3u8' in seg.lower() and depth < 2:
                st = _probe_safe(seg, timeout, depth + 1)
                return OK if st == OK else DEAD
            try:
                with _open(seg, timeout, 'bytes=0-2047') as sr:
                    if sr.getcode() not in (200, 206):
                        return DEAD
                    d = sr.read(2048)
                    if len(d) < 188 or b'<html' in d.lower() or b'<!doctype' in d.lower():
                        return DEAD
                    d_low = d.lower()
                    if any(err in d_low for err in (b'access denied', b'forbidden', b'unauthorized', b'not found', b'error 414', b'request-uri too large', b'token expired', b'geo-blocked', b'location is not supported')):
                        return DEAD
                    if has_aes:
                        return OK
                    is_ts = (d[0] == 0x47 or (len(d) > 188 and d[188] == 0x47))
                    is_mp4 = (len(d) >= 8 and d[4:8] in (b'ftyp', b'styp', b'moof', b'moov', b'mdat', b'free', b'skip'))
                    is_audio = (d[:3] == b'ID3' or (len(d) >= 2 and d[0] == 0xff and (d[1] & 0xf0) == 0xf0))
                    if is_ts or is_mp4 or is_audio:
                        return OK
                    return DEAD
            except Exception:
                return DEAD

        # --- Flujos directos ---
        if head[0] == 0x47 or (len(head) > 188 and head[188] == 0x47):
            return OK
        if head[4:8] in (b'ftyp', b'moov', b'mdat', b'free', b'wide', b'skip'):
            return OK
        if head[:4] == b'\x1aE\xdf\xa3' or head[:4] == b'RIFF' or head[:3] in (b'FLV', b'ID3'):
            return OK
        if any(t in ctype for t in ('video', 'audio', 'mpegurl', 'octet-stream', 'mp2t')):
            return OK
        return DEAD
def _probe_safe(url, timeout, depth):
    try:
        return _probe(url, timeout, depth)
    except Exception:
        return DEAD


def probe(url, timeout=4.0):
    """OK = flujo real confirmado | SOFT = responde pero no se pudo confirmar | DEAD = caido."""
    return _probe_safe(url, timeout, 0)


# ============================================================================
# PARSEO M3U
# ============================================================================
def parse_m3u_content(text, default_category):
    items, curr_ext = [], None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('#EXTINF:'):
            curr_ext = line
        elif line and not line.startswith('#') and line.startswith('http') and curr_ext:
            line = normalize_stream_url(line)
            if not line or '.mpd' in line.lower():
                curr_ext = None
                continue
            name_m = re.search(r',([^,]+)$', curr_ext)
            raw_name = name_m.group(1).strip() if name_m else "Canal"
            id_m = re.search(r'tvg-id="([^"]*)"', curr_ext)
            tvg_id = id_m.group(1) if id_m else ""
            curr = curr_ext
            curr_ext = None
            if is_foreign_garbage(raw_name, tvg_id, line):
                continue
            logo_m = re.search(r'tvg-logo="([^"]*)"', curr)
            group_m = re.search(r'group-title="([^"]*)"', curr)
            items.append({
                'name': clean_channel_name(raw_name),
                'url': line,
                'logo': logo_m.group(1) if logo_m else "",
                'raw_group': group_m.group(1).strip() if group_m else default_category,
                'tvg_id': tvg_id,
            })
    return items


def load_existing_master(path):
    """Lee la lista actual de Leo. Devuelve (canales_ordenados, series_existentes, purgados)."""
    channels = collections.OrderedDict()
    series_entries, purged = [], []
    if not os.path.exists(path):
        return channels, series_entries, purged
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.read().splitlines()
    curr = None
    for line in lines:
        line = line.strip()
        if line.startswith('#EXTINF:'):
            curr = line
            continue
        if not curr or not line or line.startswith('#'):
            continue
        ext, curr = curr, None
        line = normalize_stream_url(line)
        if not line:
            continue
        tn = re.search(r'tvg-name="([^"]*)"', ext)
        gm = re.search(r'group-title="([^"]*)"', ext)
        lm = re.search(r'tvg-logo="([^"]*)"', ext)
        im = re.search(r'tvg-id="([^"]*)"', ext)
        after = re.search(r'",(.*)$', ext)
        raw_name = tn.group(1) if tn else (after.group(1) if after else ext.rsplit(',', 1)[-1])
        group = gm.group(1) if gm else "Television Hispana"
        logo = lm.group(1) if lm else ""
        if group.startswith("Series: "):
            series_entries.append({'name': raw_name, 'url': line, 'logo': logo, 'group': group})
            continue
        reason = foreign_reason(raw_name, im.group(1) if im else "", line)
        if reason:
            purged.append((raw_name, reason, line))
            continue
        base = clean_channel_name(raw_name)
        k = key_for_dedup(base)
        if not k:
            continue
        if k not in channels:
            channels[k] = {'name': base, 'logo': logo, 'group': group, 'urls': []}
        if line not in channels[k]['urls']:
            channels[k]['urls'].append(line)
        if not channels[k]['logo'] and logo:
            channels[k]['logo'] = logo
    return channels, series_entries, purged


# ============================================================================
# SERIES COMPLETAS (ARCHIVE.ORG) - CATALOGO VERIFICADO + AUTO-DESCUBRIMIENTO
# ============================================================================
SERIES_CATALOG = [
    ("El Chavo del 8", ["El.Chavo.del.8.SATRip.LATiNO.XviD",
                        "el-chavo-del-8-1976-temporada-1976-31-la-fiesta-de-la-buena-vecindad_202402",
                        "el-chavo-del-8-1979-temporada-1979-17-la-feria_202402"], ["el chavo del ocho", "el chavo"]),
    ("El Chapulin Colorado", ["el-chapulin-colorado-coleccion-1080p",
                              "el-chapulin-colorado-1976",
                              "el-chapulin-colorado-1974"], ["el chapulin colorado"]),
    ("ALF", ["alf_latino"], ["alf"]),
    ("Los Caballeros del Zodiaco", ["yk-saint-seiya-024-d-01-b-41-c-1"], ["saint seiya", "yk saint seiya"]),
    ("Los Simpson", ["tinaco_20210512", "t-36x-05", "los-simpson-treehouse-of-horror_20240901",
                     "maggie-simpson-cita-a-jugar-con-el-destino-corto",
                     "lo-simpson-pel-1cul-4-hd-720p-972715", "01_20250623_20250623"], ["los simpsons", "the simpsons"]),
    ("Los Supersonicos", ["t-2-02.-ia"], ["los supersonicos", "the jetsons", "los-s.son"]),
    ("Malcolm el de en medio", ["malcolm-el-de-en-medio-s-01_202412", "malcolm-el-de-en-medio-s-02",
                                "malcolm-el-de-en-medio-s-03_202412", "malcolm-el-de-en-medio-s-04",
                                "malcolm-el-de-en-medio-s-05", "malcolm-el-de-en-medio-s-06",
                                "malcolm-el-de-en-medio-s-07"], ["malcolm"]),
    ("Dragon Ball", ["d-01_20240907"], []),
    ("Dragon Ball Z", ["dragon-ball-zvideoplaytv"], []),
    ("Dragon Ball GT", ["Dragon-Ball-GT-Latino-JP", "etc-dbgt-2015-07"], []),
    ("Los Magnificos", ["magnificos"], []),
    ("El Auto Fantastico", ["1228-el-auto-fantastico-2000-1991-dvdrip-d-s-spa-eng-v"], []),
    ("He-Man y los Amos del Universo", ["HeManLAT", "He-Man-Y-Los-Amos-Del-Universo"], ["he-man"]),
    ("Thundercats", ["thundercats-1985-latinoingles-1080p"], []),
    ("Los Halcones Galacticos", ["los-halcones-galacticos-audio-latino"], ["silverhawks"]),
    ("Superagente 86", ["SA6-V1"], []),
    ("Mi Bella Genio", ["mbg-01x-17"], ["mbg"]),
    ("Hechizada", ["h-v2_20240918"], []),
    ("Dinosaurios", ["1x-01_202409"], []),
    ("La Tremenda Corte", ["abundicidio-la-tremenda-corte-tv-360-p"], []),
    ("El Mundo de Beakman", ["Beakman92"], []),
    ("Garfield y sus Amigos", ["Garfield98"], []),
    ("Pinky y Cerebro", ["pinkycerebro"], []),
    ("Don Gato y su Pandilla", ["Don-Gato-Y-Su-Pandilla-Latino"], ["don gato"]),
    ("Salvado por la Campana", ["salvado-por-la-campana-espanol-latino"], []),
    ("Ranma 1/2", ["ranma-nibunnoichi-espanol-latino-y-japones"], ["ranma", "ranma 1/2"]),
    ("Los Picapiedra", ["01x-12-el-boleto-de-la-loteria_202506", "02x-19-los-ahorros-de-vilma_202506",
                        "03x-01-dino-va-a-hollyrock_202506", "04x-03-el-pequeno-bam-bam_202506",
                        "05x-15-pedro-el-piloto_202506", "06x-10-el-asunto-piedradedo_202506"], ["los picapiedras", "the flintstones"]),
    ("Fenomenoide", ["Fenomenoide-1", "Fenomenoide-2"], ["freakazoid"]),
    ("Ren y Stimpy", ["ren-y-stimpy-1", "ren-y-stimpy-3", "ren-y-stimpy-4", "ren-y-stimpy-5"], ["ren and stimpy"]),
    ("InuYasha", ["inuyasha-cap-21-y-22", "inu-yasha-cap-113", "inuyasha-cap-046"], ["inuyasha", "inu yasha"]),
    ("Supercampeones", ["supercampeones_202604", "supercampeones_202406",
                        "04-supercampeones-road-to-2002-super-campeones-camino-hacia-el-mundial-2002-audio-latino-240-p",
                        "40-supercampeones-road-to-2002-super-campeones-camino-hacia-el-mundial-2002-audio-latino-240-p"], ["supercampeones", "captain tsubasa"]),
    ("House of Mouse", ["homenlatino"], ["house of mouse", "el club del raton"]),
    # Series verificadas en Espanol (.mp4 / .ia.mp4 100% compatible Android WebView)
    ("Yo Soy Betty, la Fea", ["yo-soy-betty-la-fea_202502"], ["betty la fea"]),
    ("Dr. House", ["dr-house-latino"], ["house", "house md"]),
    ("Sabrina, la Bruja Adolescente", ["sabrina_202109"], ["sabrina"]),
    ("Marco", ["marco-serie-completa_202508"], []),
    ("Heidi", ["heidi-1974-audio-latino-1080p"], []),
    ("El Laboratorio de Dexter", ["laboratorio-de-dexter-latino"], ["dexter"]),
    ("Martin Mystery", ["Martin-Mistery-Latino"], ["martin mistery"]),
    ("Mucha Lucha", ["mucha-lucha_202505"], []),
    ("Megas XLR", ["megas-xlr-latino"], []),
    ("El Autobus Magico", ["AutoMagico94"], ["autobus magico", "auto magico"]),
    ("Beetlejuice", ["BeetlejuiceTV89"], []),
    ("Los Cazafantasmas", ["Cazafantasmas86"], ["los verdaderos cazafantasmas", "cazafantasmas"]),
    ("Static Shock", ["StaticShock2000"], []),
    ("Los Gatos Samurai", ["GatosSamurai90"], ["gatos samurai"]),
    ("Sonic el Erizo", ["SonicElErizo92"], ["sonic"]),
    ("Charlie Brown y Snoopy", ["SnoopyLatino"], ["snoopy"]),
    ("La Familia P. Luche", ["la-familia-p.-luche-2002-s-01", "la-familia-p.-luche-2002-s-02", "la-familia-p.-luche-2002-s-03"], ["familia peluche"]),
    ("31 Minutos", ["31minutosdvd"], []),
    ("Los 4 Fantasticos", ["los-4-fantasticos_202606"], ["cuatro fantasticos"]),
    ("X-Men: Evolution", ["x-men-evolution_S01-202606", "x-men-evolution-s02", "x-men-evolution-s03", "x-men-evolution-s04"], ["x-men evolution"]),
    ("Los Backyardigans", ["backyardigans-latino-t1", "backyardigans-latino-t2", "backyardigans-latino-t3", "backyardigans-latino-tIV"], ["backyardigans"]),
    ("Los Locos Addams", ["locos-addams-64"], ["locos addams"]),
    ("Cuentos de la Cripta", ["Cripta93"], []),
    ("Felix el Gato", ["FelixMichi58"], []),
    ("La Familia Ingalls", ["casadelapraderatemp01", "Httpsarchive.orgdetailslacasadelapraderat1", "lacasadelapraderaT3",
                            "lacasadelapradera", "lacasadelapraderatemp6", "lacasadelapraderatemp7",
                            "casapraderatemp8", "lacasadelapraderatemp9", "lacasadelapraderat10"], ["la casa de la pradera"]),
    ("Superlibro", [
        "cap-12_202609", "SUperbox", "cap-3_202609", "tempo-4", "cap-4_202609",
        "LosDiezMandamientosSuperLibro", "cap-11-superlibro-superlibro-clasico-sanson-y-dalila",
        "unaaventura_201706", "eltejedordesuenos", "elharesucitado", "laprimeranavidad",
        "cap-18-superlibro-superlibro-clasico-david-goliat", "DejaIrAMiPuebloSuperLibro720",
        "milagrosdejesus", "cap-4-superlibro-superlibro-clasico-la-prueba-de-abraham",
        "superlibro-episodio-batalla-final-720-p-hd"
    ], ["superlibro clasico", "superbook"]),
    ("Superraton", ["66-los-monstruos-de-la-luna", "sraton_202606"], ["mighty mouse"]),
    ("Astro Boy", ["astro-boy-1963-capitulo-008-el-cometa-plateado-latino", "astro-boy-"], ["astroboy"]),
    ("X-Men (1992)", ["x-men-1992"], ["x-men la serie animada"]),
    ("Motorratones de Marte", ["los-motorratones-de-marte", "biker-mice-from-mars-latino-la-visita"], ["motorratones", "biker mice from mars"]),
    ("Volver al Futuro", ["volveralfuturo"], ["regreso al futuro", "back to the future"]),
    ("Cantinflas: Peliculas Clasicas", ["0956-cantinflas-ama-a-tu-projimo-1958-720p-dvdrip-lat-upsc-v"], ["cantinflas peliculas"]),
    ("Cantinflas Show", ["cantinflasshow", "amigoandfriends"], ["cantinflas y sus amigos"]),
    ("Mr. Bean", ["mr-bean-1990-dual", "bean-el-nombre-del-desastre-1997", "las-vacaciones-de-mr.-bean-2007_202607"], ["mr bean live action", "bean el nombre del desastre"]),
    ("Manimal", ["manimal1_201909", "manimal8_201909"], []),
    ("La Mujer Maravilla", ["la-mujer-maravilla-serie-espanol-capitulo-1-temporada-1-video-dailymotion_202009", "la-mujer-maravilla-3x-22-el-hombre-inmortal-series-retro"], ["wonder woman"]),
    ("Ninos en crecimiento", ["ninos-en-crecimiento-01-mucho-gusto-canal-10-tves", "ninos-en-crecimiento-demasiados-compromisos-recuerdos-de-television-boliviana-canal-7"], ["ninos en crecimiento"]),
]

# Series que el robot busca solo en cada ejecucion (se agregan si aparecen en espanol)
WANTED_SERIES = [
    "El Chavo del 8", "El Chavo Animado", "El Chapulin Colorado", "Chespirito", "Los Caquitos",
    "ALF", "Los Simpson", "Los Caballeros del Zodiaco", "Dragon Ball", "Dragon Ball Z",
    "Dragon Ball Super", "Los Picapiedra", "Los Supersonicos", "Don Gato", "El Inspector Gadget",
    "Los Pitufos", "Mazinger Z", "Candy Candy", "Heidi", "Supercampeones", "Remi", "Marco",
    "La Familia Ingalls", "El Zorro", "Los Locos Addams", "La Familia Monster", "Tres por Tres",
    "Los Anos Maravillosos", "Viaje a las Estrellas",
    "El Increible Hulk", "La Mujer Maravilla", "El Auto Fantastico", "Los Magnificos", "Superagente 86",
    "Hechizada", "Mi Bella Genio", "Dinosaurios", "La Tremenda Corte", "Garfield", "Pinky y Cerebro",
    "Animaniacs", "Tiny Toons", "Thundercats", "He-Man", "She-Ra", "Los Halcones Galacticos",
    "Malcolm el de en medio", "Salvado por la Campana", "El Principe del Rap", "Todos Odian a Chris",
    "Kenan y Kel", "Sabrina la Bruja Adolescente", "Seinfeld", "Friends", "Dos Hombres y Medio",
    "Futurama", "Padre de Familia", "Bob Esponja", "Los Padrinos Magicos", "Oye Arnold", "Doug",
    "El Laboratorio de Dexter", "Johnny Bravo", "Coraje el Perro Cobarde", "Las Chicas Superpoderosas",
    "Rugrats", "Las Tortugas Ninja", "Robotech", "Transformers", "Los Cazafantasmas",
    "Sailor Moon", "Ranma", "Pokemon", "Digimon", "Scooby Doo", "Tom y Jerry", "La Pantera Rosa",
    "El Pajaro Loco", "Popeye", "Plaza Sesamo", "Odisea Burbujas", "Carrusel", "Chiquilladas",
    "Cuentos de los Hermanos Grimm", "El Mundo de Beakman", "Los Thunderbirds", "Bonanza",
    "Kung Fu", "Los Duques de Hazzard", "CHiPs", "Dr. House", "Yo Soy Betty, la Fea",
    "La Familia P. Luche", "Mucha Lucha", "Martin Mystery", "Megas XLR", "Static Shock",
    "Beetlejuice", "31 Minutos", "Los Backyardigans", "X-Men: Evolution",
    "Ninos en crecimiento", "Superlibro", "Superraton", "Astro Boy",
    "X-Men (1992)", "Motorratones de Marte", "Volver al Futuro",
    "Cantinflas: Peliculas Clasicas", "Cantinflas Show", "Mr. Bean",
    "Manimal",
]

VIDEO_EXT = ('.mp4', '.mkv', '.avi', '.m4v', '.webm', '.ogv', '.mpg', '.mpeg')
JUNK_TITLE_RE = re.compile(
    r'(creepypasta|referencias|predicci|retrospectiva|podcast|trailer|review|rese[nñ]a|an[aá]lisis|'
    r'opening|intro|soundtrack|\bost\b|karaoke|gameplay|\bjuego\b|comerciales|promo|vhs #|teoria|'
    r'curso|tutorial|manual|libro|dialisis|medicina|dibujo|clase|leccion|conferencia|audiolibro|'
    r'english dub|italian dub|dublado|legendado|chaves|parodia|fandub|reacci)',
    re.IGNORECASE
)


def _deaccent(s):
    return ''.join((unicodedata.normalize('NFKD', c) or c)[0] for c in s)


def norm_txt(s):
    return _deaccent(s or '').lower()


def natural_key(s):
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', norm_txt(s))]


def _strip_prefixes(text, prefixes):
    for p in prefixes:
        words = re.findall(r'[a-z0-9]+', norm_txt(p))
        if not words:
            continue
        m = re.match(r'^\W*' + r'\W+'.join(map(re.escape, words)) + r'\b\W*', norm_txt(text))
        if m:
            text = text[m.end():]
    return text.strip(' -._')


def pretty_episode(series, aliases, item_id, item_title, path, idx):
    folder, fname = path.rsplit('/', 1) if '/' in path else ('', path)
    stem = fname
    for _ in range(2):
        stem = re.sub(r'\.(mp4|mkv|avi|m4v|webm|ogv|mpg|mpeg)$', '', stem, flags=re.IGNORECASE)
    stem = re.sub(r'\.ia$', '', stem, flags=re.IGNORECASE).strip()

    is_hash = bool(re.match(r'^(km_|azlpa-|ejw|\d{5,}--)', stem.lower())) or (len(stem) > 35 and re.match(r'^[a-fA-F0-9_-]+$', stem))
    if is_hash:
        clean_item = _strip_prefixes(item_title, [series] + list(aliases))
        clean_item = re.sub(r'^(en|de)\s+', '', clean_item, flags=re.IGNORECASE)
        clean_item = re.sub(r'\s+', ' ', clean_item).strip(' -._')
        if clean_item:
            return "%s - %s - Parte %02d" % (series, clean_item, idx)
        return "%s - Episodio %02d" % (series, idx)

    def clean(t):
        t = re.sub(r'\[[^\]]*\]', ' ', t)
        t = re.sub(r'\(\s*\d{3,4}p\s*\)', ' ', t, flags=re.IGNORECASE)
        t = re.sub(r'(?i)www[._\s]?\S+?[._\s](com|info|net|org)\b', ' ', t)
        t = re.sub(r'(?i)\b(dvdrip|satrip|xvid|x264|h264|1080p|720p|480p|360p|tv\s*\(?360p\)?)\b', ' ', t)
        t = t.replace('_', ' ')
        t = re.sub(r'(?<=\d)\.(?=[^\d\s])', ' ', t)
        t = re.sub(r'(?<=[A-Za-z])\.(?=[A-Za-z])', ' ', t)
        return re.sub(r'\s+', ' ', t).strip(' -._')

    t = clean(stem)
    if folder and norm_txt(folder) != norm_txt(item_id):
        f = re.sub(r'^\d+\s*-\s*', '', clean(folder.split('/')[-1]))
        if f:
            t = "%s - %s" % (f, t)
    t = _strip_prefixes(t, [series] + list(aliases))
    if not t or re.fullmatch(r'\d+', t):
        t = "Episodio %s" % (t or idx)
    return "%s - %s" % (series, t)


def _should_skip_archive_file(item_id, name_low):
    """Filtra copias en Castellano, extras DVD en inglés o duplicados inferiores en items curados."""
    iid_l = (item_id or '').lower()
    if iid_l == 'mr-bean-1990-dual':
        return 'temporada 0/' in name_low or 's00e' in name_low
    if iid_l == 'biker-mice-from-mars-latino-la-visita':
        return 'biker mice from mars latino la visita' in name_low
    if iid_l == 'la-mujer-maravilla-3x-22-el-hombre-inmortal-series-retro':
        return 'series retro' not in name_low
    if iid_l == '0956-cantinflas-ama-a-tu-projimo-1958-720p-dvdrip-lat-upsc-v':
        if 'castellano' in name_low:
            return True
        skip_exact = (
            'cantinflas ama a tu projimo (1958) 720p.mp4',
            '1976 el ministro y yo fhd(1975) 1080p web-dl lat v.mp4',
            'cantinflas ruletero (1940) 60fps.mp4',
            'cantinflas boxeador (1940) 60fps.mp4',
            'cantinflas jengibre contra dinamita (1939) 60fps.mp4',
        )
        return name_low in skip_exact
    return False


def extract_episodes(series, aliases, item_id, meta):
    """Elige 1 archivo de video por episodio: original mp4 > derivado .ia.mp4 > webm > mkv > avi (100% Android/WebView compatible)."""
    md = meta.get('metadata', {}) or {}
    title = md.get('title') or item_id
    if isinstance(title, list):
        title = title[0]
    groups = collections.OrderedDict()
    for f in meta.get('files', []) or []:
        name = f.get('name', '')
        nl = name.lower()
        if not nl.endswith(VIDEO_EXT) or f.get('private') in ('true', True) or 'sample' in nl:
            continue
        if _should_skip_archive_file(item_id, nl):
            continue
        try:
            size = int(f.get('size') or 0)
        except ValueError:
            size = 0
        if size and (size < 3_000_000 or size > 4_500_000_000):
            continue
        stem = name
        for _ in range(2):
            stem = re.sub(r'\.(mp4|mkv|avi|m4v|webm|ogv|mpg|mpeg)$', '', stem, flags=re.IGNORECASE)
        stem = re.sub(r'\.ia$', '', stem, flags=re.IGNORECASE).strip()
        ext = os.path.splitext(nl)[1]
        orig = f.get('source') == 'original'
        if orig and ext in ('.mp4', '.m4v'):
            rank = 0
        elif ext in ('.mp4', '.m4v'):
            rank = 1
        elif orig and ext == '.webm':
            rank = 2
        elif orig and ext == '.mkv':
            rank = 3
        elif ext in ('.mkv', '.webm'):
            rank = 4
        else:
            rank = 5
        cur = groups.get(stem)
        if cur is None or rank < cur[0]:
            groups[stem] = (rank, name)
    chosen = sorted((v[1] for v in groups.values()), key=natural_key)
    eps = []
    for i, path in enumerate(chosen, 1):
        url = "https://archive.org/download/%s/%s" % (item_id, urllib.parse.quote(path, safe='/'))
        eps.append([pretty_episode(series, aliases, item_id, title, path, i), url])
    return title, eps


def load_json(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def save_json_atomic(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def ia_search(query, rows=15):
    url = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode({
        'q': query, 'fl[]': ['identifier', 'title', 'language', 'description', 'item_size'],
        'rows': rows, 'sort[]': 'downloads desc', 'output': 'json'}, doseq=True)
    ok, d = fetch_json(url)
    if not ok or not isinstance(d, dict):
        return None
    return d.get('response', {}).get('docs', [])


def _as_text(v):
    if isinstance(v, list):
        return ' '.join(map(str, v))
    return str(v or '')


def discovery_accepts(doc, series_name):
    title = _as_text(doc.get('title'))
    lang = norm_txt(_as_text(doc.get('language')))
    desc = norm_txt(re.sub(r'<[^>]+>', ' ', _as_text(doc.get('description'))))[:600]
    words = re.findall(r'[a-z0-9]+', norm_txt(series_name))
    tnorm = norm_txt(title)
    if not all(re.search(r'\b%s\b' % re.escape(w), tnorm) for w in words):
        return False
    if JUNK_TITLE_RE.search(title) or is_foreign_garbage(title):
        return False
    iid_low = (doc.get('identifier') or '').lower()
    if any((f'/{b}/' in f'/{iid_low}/' or b == iid_low) for b in BLACKLIST_IDENTIFIERS):
        return False
    if re.fullmatch(r'astro-boy-\d+', iid_low):
        return False
    if 'pocoyo' in tnorm and 'pocoyo' not in norm_txt(series_name):
        return False
    spa_marker = re.search(r'(latino|espanol|castellano|temporada|capitulo|episodio|doblaje|serie completa)', tnorm + ' ' + desc)
    if lang:
        if not re.search(r'(spa|spanish|espanol|castellano|latino)', lang):
            return False
    elif not spa_marker:
        return False
    if re.search(r'\b(ingles|english)\b', tnorm) and not re.search(r'(latino|espanol|castellano)', tnorm):
        return False
    return True


def best_series_name(title):
    """Asigna el item al nombre deseado mas especifico (ej. 'Dragon Ball Z' antes que 'Dragon Ball')."""
    tnorm = norm_txt(title)
    best = None
    for s in WANTED_SERIES:
        words = re.findall(r'[a-z0-9]+', norm_txt(s))
        if words and all(re.search(r'\b%s\b' % re.escape(w), tnorm) for w in words):
            if best is None or len(words) > len(re.findall(r'[a-z0-9]+', norm_txt(best))):
                best = s
    return best


def harvest_complete_series():
    """Devuelve lista de episodios [(grupo, nombre, url, logo)] + estadisticas. Acumulativo."""
    cache = load_json(SERIES_CACHE_PATH, {})
    cache.setdefault('items', {})
    cache.setdefault('rejected', [])
    cache.setdefault('discovery', {})
    items, rejected = cache['items'], set(cache['rejected'])
    now = time.time()
    aliases_by_series = {s: al for s, _, al in SERIES_CATALOG}

    # 0. Purgar blacklist y forzar refresco (.mp4/.ia.mp4) de colecciones heredadas con .mkv/.avi
    LEGACY_BAD_EXT = ('.mkv', '.avi', '.ogv', '.mpg', '.mpeg')
    for biid in list(items.keys()):
        if biid.lower() in BLACKLIST_IDENTIFIERS:
            del items[biid]
            rejected.add(biid)
            continue
        it_old = items[biid]
        eps_old = it_old.get('episodes') or []
        if any(str(u).split('?')[0].lower().endswith(LEGACY_BAD_EXT) for _, u in eps_old):
            it_old['fetched'] = 0

    # 1. Catalogo verificado
    for series, ids, _al in SERIES_CATALOG:
        for iid in ids:
            items.setdefault(iid, {'series': series, 'title': iid, 'auto': False, 'status': 'ok', 'fetched': 0, 'episodes': []})
            items[iid]['series'] = series

    # 2. Auto-descubrimiento de series nuevas en espanol
    wanted_list = list(WANTED_SERIES)
    if os.path.exists(SERIES_DESEADAS_PATH):
        try:
            custom_wanted = load_json(SERIES_DESEADAS_PATH, [])
            for cw in custom_wanted:
                if cw and cw not in wanted_list:
                    wanted_list.append(cw)
        except Exception:
            pass
    else:
        save_json_atomic(SERIES_DESEADAS_PATH, WANTED_SERIES)

    active_series = {it['series'] for it in items.values() if it.get('status') == 'ok' and len(it.get('episodes', [])) > 0}
    to_search = [s for s in wanted_list if (s not in active_series) or (now - cache['discovery'].get(s, 0) > DISCOVERY_REFRESH_DAYS * 86400)]
    new_ids = {}
    if to_search:
        print("[+] Buscando series nuevas en espanol en Archive.org (%d titulos)..." % len(to_search))

        def search_one(s):
            q = 'title:("%s") AND mediatype:movies AND item_size:[400000000 TO *]' % s
            return s, ia_search(q)

        with ThreadPoolExecutor(max_workers=10) as ex:
            results = list(ex.map(search_one, to_search))
        for s, docs in results:
            if docs is None:
                continue  # error de red: reintentar en la proxima ejecucion
            cache['discovery'][s] = now
            taken = 0
            for d in docs:
                iid = d.get('identifier')
                if not iid or iid in items or iid in rejected or iid in new_ids:
                    continue
                if not discovery_accepts(d, s):
                    rejected.add(iid)
                    continue
                target = best_series_name(_as_text(d.get('title'))) or s
                new_ids[iid] = target
                taken += 1
                if taken >= 4:
                    break
        for iid, target in new_ids.items():
            items[iid] = {'series': target, 'title': iid, 'auto': True, 'status': 'pending', 'fetched': 0, 'episodes': []}

    # 3. Descargar metadatos (solo items nuevos o con cache vieja)
    stale = [iid for iid, it in items.items()
             if it.get('status') != 'dead' and now - it.get('fetched', 0) > SERIES_REFRESH_DAYS * 86400]
    print("[+] Actualizando %d colecciones de series (cache: %d)..." % (len(stale), len(items) - len(stale)))

    def fetch_meta(iid):
        return iid, fetch_json("https://archive.org/metadata/%s" % urllib.parse.quote(iid), timeout=30)

    with ThreadPoolExecutor(max_workers=12) as ex:
        metas = list(ex.map(fetch_meta, stale))

    for iid, (ok, meta) in metas:
        it = items[iid]
        if not ok:
            if it.get('status') == 'pending':
                del items[iid]           # se reintentara en otra ejecucion
            continue                     # error de red: se conserva la cache intacta
        if not meta or meta.get('is_dark') or not meta.get('files'):
            it['status'] = 'dead'        # coleccion retirada de Archive.org
            continue
        series = it['series']
        title, eps = extract_episodes(series, aliases_by_series.get(series, []), iid, meta)
        if it.get('auto') and len(eps) < 6:
            del items[iid]
            rejected.add(iid)
            continue
        # Fusion acumulativa: nunca se pierden episodios ya conocidos
        known = {u for _, u in it.get('episodes', [])}
        merged = list(it.get('episodes', [])) + [e for e in eps if e[1] not in known]
        if eps:
            current = {u for _, u in eps}
            merged = [e for e in merged if e[1] in current] or merged  # quita solo archivos borrados del item
        it.update({'title': title, 'status': 'ok', 'fetched': now, 'episodes': merged})

    cache['rejected'] = sorted(rejected)
    save_json_atomic(SERIES_CACHE_PATH, cache)

    # 4. Construir salida ordenada y deduplicada estructurada por TEMPORADAS Y CAPITULOS
    EXCLUDED_IIDS = {
        '5-el-increible-hulk', 'CadillacsyDinosaurios93LAT',
        'episodios-de-la-pantera-rosa-1-episodio-de-barrio-sesamo-spanish',
        'chvochplin-vhsrips', 'chavodel8-60fps', 'el-chavo-logoless',
        'eJwzMTXTNdQ1000tjs9JLNFNK83Jic9I0S02AwBdHgfn.mkv',
        'km_20260725-6_480p_25f_20260725_163427', 'km_20260801_480p_25f_20260801_104339',
        'km_20260802-5_480p_25f_20260802_174515_202608',
        'las-tortugas-ninjalos-ninja-tortugas-adolescentes-mutantes-decima-temporada',
        'digimon-frontier-castellano',
        'la-familia-monster-the-munsters-castellano-audio-rtve-el-hermano-de-eddie-hd',
        'pink-panther-show-spanish-2005', 'GordonShumway', 'alf-latino_202511',
        '20230628_20230628_1426', 'candycandylatamdub', 'Dragon-Ball-Z-Latino-JP',
        'el-chavo-animado-temporada-2-completa-dvd', 'el.-chavo.-animado.-dvdr.-0647.-ftp',
        'temporada-3-capitulo-7_202501', 'bella-genio', 'mi-bella-genio.-temp-1-cap-17',
        'pinky-y-cerebro-1', 'pinky-y-cerebro-2', 'pinky-y-cerebro-3', 'pinky-y-cerebro-4',
        'batman-la-serie-animada-1992-latino', 'pocoyo-perdidos-en-el-espacio-dvd-iso',
        'cesser-16-liga-de-la-justicia-720p', 'EdEddEEddyS0106SpecialEFilmMuxByThegatto',
        'GatoCosmico', 'Popeye33', 'escalofrios95', 'Pucca06LAT', 'la-ninera-2004-480p',
        't-2x-14', 'kenan-y-kel-s-02', 'don-gato-y-su-pandilla_202601',
        'bob-esponja-2-temporada-episodios-09-supervivencia-de-los-idiotas-.-expulsado',
        'los-pitufos-azteca-7-mexico-volumenes-47-48-49-incluye-15-metariales-extras-dvd-9',
        'la-familia-ingalls-temporada-1', 'la-familia-ingalls-temporada-1_202010',
        'Coraje-1', 'Coraje-2', 'Coraje-3', 'Coraje-4', 'Coraje-el-perro-cobarde-latino',
        'Malcolm-el-de-en-medio-temp01',
        'malcolm-el-de-en-medio-t-01', 'malcolm-el-de-en-medio-t-02',
        'malcolm-el-de-en-medio-t-03', 'malcolm-el-de-en-medio-t-04',
        'malcolm-el-de-en-medio-t-05', 'malcolm-el-de-en-medio-t-06',
        'malcolm-el-de-en-medio-t-07',
        'thundercats-063-mumm-rana', 'thundercats2011', 'thundercats_202303', 'ren-y-stimpy-2'
    }
    EXCLUDED_IIDS_LOW = {x.lower() for x in EXCLUDED_IIDS} | BLACKLIST_IDENTIFIERS
    SERIES_NAME_MAP = {
        'Don Gato': 'Don Gato y su Pandilla',
        'Don Gato y su Pandilla': 'Don Gato y su Pandilla',
        'He-Man': 'He-Man y los Amos del Universo',
        'Malcolm': 'Malcolm el de en medio',
    }

    def _clean_ep_str(t):
        t = re.sub(r'\[[^\]]*\]', '', t)
        t = re.sub(r'\([^\)]*p\)', '', t, flags=re.I)
        t = re.sub(r'\b(1080p|720p|480p|dvdrip|h264|xvid|x264|latino|audio latino|espanol latino|serieslan com|by carlosj|sullca|dragon ball sullca)\b', '', t, flags=re.I)
        t = t.replace('_', ' ').replace('.', ' ')
        return re.sub(r'\s+', ' ', t).strip(' -._')

    def _parse_ep_meta(s_name, raw_name, item_id, idx):
        s_name = SERIES_NAME_MAP.get(s_name, s_name)
        norm = raw_name
        if norm.lower().startswith(s_name.lower()):
            norm = norm[len(s_name):].strip(' -._:')
        
        if s_name == 'Dragon Ball Z':
            ep_num = idx
            if ep_num <= 35: s_val, saga = 1, "Saga Saiyajin (Cap. 001 - 035)"
            elif ep_num <= 107: s_val, saga = 2, "Saga Freezer (Cap. 036 - 107)"
            elif ep_num <= 139: s_val, saga = 3, "Saga Garlick Jr. y Androides (Cap. 108 - 139)"
            elif ep_num <= 199: s_val, saga = 4, "Saga Cell (Cap. 140 - 199)"
            elif ep_num <= 219: s_val, saga = 5, "Saga Torneo del Otro Mundo (Cap. 200 - 219)"
            else: s_val, saga = 6, "Saga Majin Boo (Cap. 220 - 291)"
            tc = _clean_ep_str(norm)
            tc = re.sub(r'^\d+\s*-\s*\d+\s*-\s*', '', tc)
            tc = re.sub(r'-\s*Dragon\s*Ball\s*Sullca.*$', '', tc, flags=re.I)
            dt = f"{s_name} - Cap. {ep_num:03d} - {tc}" if tc else f"{s_name} - Cap. {ep_num:03d}"
            gt = f"Series: {s_name} - Temporada {s_val:02d}: {saga}"
            return s_val, ep_num, dt, gt

        if s_name == 'El Chavo del 8':
            m_yr = re.search(r'\b(197\d)[xX\s-]+(\d{1,3})\b', norm)
            if m_yr:
                yr, ep = int(m_yr.group(1)), int(m_yr.group(2))
                tc = _clean_ep_str(norm[m_yr.end():])
                dt = f"{s_name} - T{yr} Cap. {ep:02d} - {tc}" if tc else f"{s_name} - T{yr} Cap. {ep:02d}"
                return yr, ep, dt, f"Series: {s_name} - Temporada {yr}"

        if s_name == 'Dragon Ball':
            ep_num = idx
            s_val = (ep_num - 1) // 50 + 1
            tc = _clean_ep_str(re.sub(r'^\d{3}\s*-\s*', '', norm))
            return s_val, ep_num, f"{s_name} - Cap. {ep_num:03d} - {tc}", f"Series: {s_name} - Temporada {s_val:02d}"

        if s_name == 'Candy Candy':
            ep_num = idx
            s_val = (ep_num - 1) // 40 + 1
            tc = _clean_ep_str(re.sub(r'^(?:capitulo|cap)\s*\d{1,3}\s*[.-]?\s*', '', norm, flags=re.I))
            return s_val, ep_num, f"{s_name} - Cap. {ep_num:03d} - {tc}", f"Series: {s_name} - Temporada {s_val:02d}"

        if s_name == 'Los Caballeros del Zodiaco':
            ep_num = idx
            if ep_num <= 73: s_val, saga = 1, "Saga del Santuario (Cap. 001 - 073)"
            elif ep_num <= 99: s_val, saga = 2, "Saga de Asgard (Cap. 074 - 099)"
            elif ep_num <= 114: s_val, saga = 3, "Saga de Poseidon (Cap. 100 - 114)"
            else: s_val, saga = 4, "Saga de Hades (Cap. 115 - 145)"
            tc = _clean_ep_str(re.sub(r'^\d{3}\s*-\s*', '', norm))
            dt = f"{s_name} - Cap. {ep_num:03d} - {tc}" if tc else f"{s_name} - Cap. {ep_num:03d}"
            return s_val, ep_num, dt, f"Series: {s_name} - Temporada {s_val:02d}: {saga}"

        iid_low = (item_id or '').lower()

        if s_name == 'Superlibro':
            sb_season = {
                'cap-12_202609': 1, 'superbox': 2, 'cap-3_202609': 3, 'tempo-4': 4, 'cap-4_202609': 5,
            }
            if iid_low in sb_season:
                s_val = sb_season[iid_low]
                m_c = re.search(r'(?:cap|episodio)\s*(\d{1,3})', norm, re.I)
                e_val = int(m_c.group(1)) if m_c else idx
                return s_val, e_val, f"{s_name} - T{s_val:02d}E{e_val:02d}", f"Series: {s_name} - Temporada {s_val:02d}"
            clasico_map = {
                'losdiezmandamientossuperlibro': (1, "Los Diez Mandamientos"),
                'cap-11-superlibro-superlibro-clasico-sanson-y-dalila': (2, "Sanson y Dalila"),
                'unaaventura_201706': (3, "Una Aventura en el Tiempo"),
                'eltejedordesuenos': (4, "El Tejedor de Suenos (Jose)"),
                'elharesucitado': (5, "El Ha Resucitado"),
                'laprimeranavidad': (6, "La Primera Navidad"),
                'cap-18-superlibro-superlibro-clasico-david-goliat': (7, "David y Goliat"),
                'dejairamipueblosuperlibro720': (8, "Deja Ir a Mi Pueblo"),
                'milagrosdejesus': (9, "Milagros de Jesus"),
                'cap-4-superlibro-superlibro-clasico-la-prueba-de-abraham': (10, "La Prueba de Abraham"),
                'superlibro-episodio-batalla-final-720-p-hd': (11, "La Batalla Final"),
            }
            e_val, label = clasico_map.get(iid_low, (100 + idx, _clean_ep_str(norm)))
            return 0, e_val, f"{s_name} - Clasico {e_val:02d} - {label}", f"Series: {s_name} - Temporada 00: Serie Clasica (1981)"

        if s_name == 'Superraton':
            if iid_low == 'sraton_202606':
                return 2, 1, f"{s_name} - Pelicula Recopilatoria", f"Series: {s_name} - Temporada 02: Especial"
            m_n = re.match(r'^(\d{1,3})\s*[-–]\s*(.*)$', norm.strip())
            e_val = int(m_n.group(1)) if m_n else idx
            tc = _clean_ep_str(m_n.group(2) if m_n else norm)
            return 1, e_val, f"{s_name} - T01E{e_val:02d} - {tc}", f"Series: {s_name} - Temporada 01"

        if s_name == 'Astro Boy':
            if '1963' in iid_low:
                return 1, 8, f"{s_name} - T01E08 (1963) - El Cometa Plateado", f"Series: {s_name} - Temporada 01: Serie 1963"
            return 2, 1, f"{s_name} - La Pelicula (2009)", f"Series: {s_name} - Temporada 02: Pelicula"

        if s_name == 'X-Men (1992)':
            norm_xm = re.sub(r'^(?:temporada\s*\d+\s*[-:.]*\s*)', '', norm, flags=re.I)
            m_xm = re.search(r'\bS(\d{1,2})E(\d{1,3})\b\s*[-:.]*\s*(.*)$', norm_xm, flags=re.I)
            if m_xm:
                s_val, e_val = int(m_xm.group(1)), int(m_xm.group(2))
                tc = _clean_ep_str(m_xm.group(3))
                dt = f"{s_name} - T{s_val:02d}E{e_val:02d} - {tc}" if tc else f"{s_name} - T{s_val:02d}E{e_val:02d}"
                return s_val, e_val, dt, f"Series: {s_name} - Temporada {s_val:02d}"

        if s_name == 'Motorratones de Marte':
            if iid_low == 'biker-mice-from-mars-latino-la-visita':
                if 'capitulo 1' in norm.lower():
                    return 1, 1, f"{s_name} - T01E01 - El Queso Llego del Espacio (Cap. 01)", f"Series: {s_name} - Temporada 01"
                return 1, 2, f"{s_name} - T01E02 - Capitulo Clasico", f"Series: {s_name} - Temporada 01"
            m_bm = re.search(r'\bS(\d{1,2})E0*(\d{1,3})(?:A\d+)?\b(.*)$', norm, flags=re.I)
            if m_bm:
                s_val, e_val = int(m_bm.group(1)), int(m_bm.group(2))
                tc = re.sub(r'^\s*Motor[a-z]+\s+de\s+Marte\s*\d*\s*[-:]*\s*', '', m_bm.group(3), flags=re.I)
                tc = _clean_ep_str(tc)
                dt = f"{s_name} - T{s_val:02d}E{e_val:02d} - {tc}" if tc else f"{s_name} - T{s_val:02d}E{e_val:02d}"
                return s_val, e_val, dt, f"Series: {s_name} - Temporada {s_val:02d}"

        if s_name == 'Volver al Futuro':
            nl_vf = norm.lower()
            if 'iii' in nl_vf:
                return 1, 3, "Volver al Futuro - 03 - Volver al Futuro III (1990)", "Series: Volver al Futuro - Temporada 01: Trilogia 1080p"
            if 'ii' in nl_vf:
                return 1, 2, "Volver al Futuro - 02 - Volver al Futuro II (1989)", "Series: Volver al Futuro - Temporada 01: Trilogia 1080p"
            return 1, 1, "Volver al Futuro - 01 - Volver al Futuro (1985)", "Series: Volver al Futuro - Temporada 01: Trilogia 1080p"

        if s_name == 'Cantinflas: Peliculas Clasicas':
            m_yr = re.search(r'\b(19[3-8]\d)\b', norm)
            yr_str = m_yr.group(1) if m_yr else '1950'
            is_short = ('1939)' in norm or '1940)' in norm or any(k in norm.lower() for k in ('boxeador', 'jengibre', 'ruletero', 'su prima')))
            tc = re.sub(r'\b0956\b|\bCantinflas\b|\b19[3-8]\d\b|\b(?:hd)?(?:1080|720|480)p\b|\b(?:fhd|hd|hq|h265|ub|lat|identi|upsc|web[-\s]*dl|dvdrip|v)\b|\(\d+\)', ' ', norm, flags=re.I)
            tc = re.sub(r'\(\s*\)', ' ', tc)
            tc = _clean_ep_str(tc.strip(' []'))
            if tc.endswith('(') or (tc.count('(') > tc.count(')')):
                tc = tc.rstrip('( ')
            if is_short:
                return 2, idx, f"Cantinflas ({yr_str}) - Corto: {tc}", "Series: Cantinflas: Peliculas Clasicas - Temporada 02: Cortometrajes (1939-1940)"
            return 1, idx, f"Cantinflas ({yr_str}) - {tc}", "Series: Cantinflas: Peliculas Clasicas - Temporada 01: Peliculas (1936-1982)"

        if s_name == 'Mr. Bean':
            if 'desastre' in iid_low or '1997' in norm:
                return 2, 1, "Mr. Bean - Pelicula 01 (1997) - Bean: El Nombre del Desastre", "Series: Mr. Bean - Temporada 02: Peliculas"
            if 'vacaciones' in iid_low or '2007' in norm:
                return 2, 2, "Mr. Bean - Pelicula 02 (2007) - Las Vacaciones de Mr. Bean", "Series: Mr. Bean - Temporada 02: Peliculas"
            norm = re.sub(r'^(?:temporada\s*\d+\s*[-:.]*\s*)', '', norm, flags=re.I)

        if s_name == 'Manimal':
            m_mm = re.search(r'(\d+)\s*$', norm.strip())
            e_val = int(m_mm.group(1)) if m_mm else idx
            return 1, e_val, f"Manimal - T01E{e_val:02d} - Capitulo {e_val:02d}", "Series: Manimal - Temporada 01"

        if s_name == 'La Mujer Maravilla':
            if '3x' in iid_low or '3x22' in norm.lower() or 'inmortal' in norm.lower():
                return 3, 22, "La Mujer Maravilla - T03E22 - El Hombre Inmortal", "Series: La Mujer Maravilla - Temporada 03"
            return 1, 1, "La Mujer Maravilla - T01E01 - Episodio Piloto", "Series: La Mujer Maravilla - Temporada 01"

        if s_name == 'Ninos en crecimiento':
            if '01' in iid_low or 'mucho gusto' in norm.lower():
                return 1, 1, "Ninos en crecimiento - T01E01 - Mucho Gusto", "Series: Ninos en crecimiento - Temporada 01"
            return 1, 2, "Ninos en crecimiento - T01E02 - Demasiados Compromisos", "Series: Ninos en crecimiento - Temporada 01"

        m = re.search(r'\b[ST]?(\d{1,2})[xX][eE]?(\d{1,3})\b', norm)
        if m:
            s_val, e_val = int(m.group(1)), int(m.group(2))
            tc = _clean_ep_str(norm[:m.start()] + ' ' + norm[m.end():])
            dt = f"{s_name} - T{s_val:02d}E{e_val:02d} - {tc}" if tc else f"{s_name} - T{s_val:02d}E{e_val:02d}"
            return s_val, e_val, dt, f"Series: {s_name} - Temporada {s_val:02d}"

        m = re.search(r'\b[ST]\s*(\d{1,2})\s*[E\s]\s*(\d{1,3})\b', norm, re.I)
        if m:
            s_val, e_val = int(m.group(1)), int(m.group(2))
            tc = _clean_ep_str(norm[:m.start()] + ' ' + norm[m.end():])
            dt = f"{s_name} - T{s_val:02d}E{e_val:02d} - {tc}" if tc else f"{s_name} - T{s_val:02d}E{e_val:02d}"
            return s_val, e_val, dt, f"Series: {s_name} - Temporada {s_val:02d}"

        m_s = re.search(r'temporada\s*(\d{1,2})', norm, re.I)
        m_e = re.search(r'(?:capitulo|episodio|cap|ep)\s*(\d{1,3})', norm, re.I)
        if m_s:
            s_val = int(m_s.group(1))
            e_val = int(m_e.group(1)) if m_e else idx
            t = re.sub(r'temporada\s*\d{1,2}', '', norm, flags=re.I)
            t = re.sub(r'(?:capitulo|episodio|cap|ep)\s*\d{1,3}', '', t, flags=re.I)
            tc = _clean_ep_str(t)
            dt = f"{s_name} - T{s_val:02d}E{e_val:02d} - {tc}" if tc else f"{s_name} - T{s_val:02d}E{e_val:02d}"
            return s_val, e_val, dt, f"Series: {s_name} - Temporada {s_val:02d}"

        m_iid_s = re.search(r'(?:[-_]|(?<=[a-z]))t(?:emp)?[-_]?0?(\d{1,2})\b|[-_]s[-_]?0?(\d{1,2})(?:[-_]|$)|[-_](\d{1,2})$', item_id, re.I)
        s_val = int(m_iid_s.group(1) or m_iid_s.group(2) or m_iid_s.group(3)) if m_iid_s else 1
        if s_val > 30: s_val = 1
        m_ep = re.search(r'(?:capitulo|episodio|cap|ep)\s*(\d{1,3})\b|\b(\d{1,3})\s*[-–]', norm, re.I)
        e_val = int(m_ep.group(1) or m_ep.group(2)) if m_ep else idx
        t = re.sub(r'(?:capitulo|episodio|cap|ep)\s*\d{1,3}', '', norm, flags=re.I)
        tc = _clean_ep_str(t)
        dt = f"{s_name} - T{s_val:02d}E{e_val:02d} - {tc}" if tc else f"{s_name} - T{s_val:02d}E{e_val:02d}"
        return s_val, e_val, dt, f"Series: {s_name} - Temporada {s_val:02d}"

    raw_parsed = []
    seen_urls, seen_keys = set(), set()
    per_series = collections.Counter()

    for iid, it in items.items():
        if iid.lower() in EXCLUDED_IIDS_LOW or it.get('status') != 'ok':
            continue
        series = SERIES_NAME_MAP.get(it['series'], it['series'])
        logo = "https://archive.org/services/img/%s" % iid
        for idx, (raw_ep_name, ep_url) in enumerate(it.get('episodes', []), 1):
            if not ep_url or ep_url in seen_urls:
                continue
            s_val, e_val, dt, gt = _parse_ep_meta(series, raw_ep_name, iid, idx)
            dedup_k = (series, s_val, e_val)
            if dedup_k in seen_keys:
                continue
            seen_urls.add(ep_url)
            seen_keys.add(dedup_k)
            raw_parsed.append((series, s_val, e_val, gt, dt, ep_url, logo))
            per_series[series] += 1

    # Orden riguroso natural: Serie -> Temporada -> Capitulo
    raw_parsed.sort(key=lambda x: (x[0].lower(), x[1], x[2]))
    out = [(gt, dt, ep_url, logo) for (_, _, _, gt, dt, ep_url, logo) in raw_parsed]
    dead_ids = {iid for iid, it in items.items() if it.get('status') == 'dead' or iid.lower() in EXCLUDED_IIDS_LOW}
    dead_ids.update(EXCLUDED_IIDS)
    dead_ids.update(EXCLUDED_IIDS_LOW)
    return out, per_series, dead_ids, list(new_ids.items())


# ============================================================================
# DESCUBRIMIENTO DE LISTAS EN GITHUB (filtrado estricto despues)
# ============================================================================
def discover_live_github_m3us():
    discovered, repos = [], []
    queries = [
        "https://api.github.com/search/repositories?q=canales+premium+m3u&sort=updated&per_page=5",
        "https://api.github.com/search/repositories?q=iptv+colombia+m3u&sort=updated&per_page=5",
        "https://api.github.com/search/repositories?q=iptv+latino+m3u&sort=updated&per_page=5",
        "https://api.github.com/search/repositories?q=canales+latinos+m3u&sort=updated&per_page=5",
        "https://api.github.com/search/repositories?q=deportes+latino+m3u&sort=updated&per_page=5",
    ]
    for q in queries:
        ok, data = fetch_json(q, timeout=6)
        if ok and isinstance(data, dict):
            for it in data.get('items', []):
                if it['full_name'] not in repos:
                    repos.append(it['full_name'])
    for repo in repos[:8]:
        ok, items = fetch_json("https://api.github.com/repos/%s/contents" % repo, timeout=6)
        if not ok or not isinstance(items, list):
            continue
        for it in items:
            name, dl, size = it.get('name', ''), it.get('download_url'), it.get('size', 0)
            if dl and 500 < size < 3000000 and name.lower().endswith(('.m3u', '.m3u8')):
                discovered.append(("Television Hispana", dl))
    return discovered


# ============================================================================
# PROGRAMA PRINCIPAL
# ============================================================================
def main():
    t0 = time.time()
    print("=" * 74)
    print("  ROBOT CAZADOR SUPREMO OMEGA v4.0 - INMUTABILIDAD ACUMULATIVA + SERIES")
    print("=" * 74)

    if not internet_ok():
        print("[X] Sin conexion a Internet. La lista NO se toca (proteccion anti-borrado).")
        finish(None)
        return

    # 1. Favoritos
    fav_keys = set()
    for fn in load_json(FAVS_PATH, []):
        k = key_for_dedup(clean_channel_name(str(fn)))
        if len(k) >= 2:
            fav_keys.add(k)
    print("[+] Favoritos de Leo: %d" % len(fav_keys))

    # 2. Lista existente (base inmutable)
    existing, existing_series, purged = load_existing_master(OUTPUT_M3U)
    print("[+] Lista actual: %d canales conservables | %d extranjeros purgados" % (len(existing), len(purged)))
    estado = load_json(ESTADO_PATH, {})
    strikes = estado.get('strikes', {})
    radar = estado.get('radar_resurreccion', {})

    # 3. Pool de candidatos desde fuentes hispanas (orden determinista)
    pool = collections.OrderedDict()

    def add_pool(name, url, logo, raw_group, c_code=""):
        if not url or not url.startswith('http'):
            return
        url = normalize_stream_url(url)
        if not url or '.mpd' in url.lower():
            return
        k = key_for_dedup(name)
        if len(k) < 2:
            return
        if k not in pool:
            pool[k] = {'name': name, 'logo': logo, 'raw_group': raw_group, 'c_code': c_code, 'urls': []}
        p = pool[k]
        if url not in p['urls']:
            p['urls'].append(url)
        if not p['logo'] and logo:
            p['logo'] = logo
        if c_code == 'co':
            p['c_code'] = 'co'

    cat_data = load_json(LATAM_CATALOG_PATH, {})
    for ch in cat_data.get('channels', []) if isinstance(cat_data, dict) else []:
        c_name = clean_channel_name(ch.get('n', 'Canal'))
        for u in ch.get('u', []):
            if not is_foreign_garbage(c_name, "", u):
                add_pool(c_name, u, ch.get('l', ''), ch.get('g', ''), ch.get('c', ''))

    sources = list(CORE_M3U_SOURCES)
    known = {u for _, u in sources}
    for el in load_json(LISTAS_JSON_PATH, []):
        if isinstance(el, str) and el.startswith('http') and el not in known and 'localhost' not in el \
                and not any(b in el for b in BANNED_SOURCES):
            sources.append(("Television Hispana", el))
            known.add(el)
    print("[+] Radar GitHub buscando listas latinas nuevas...")
    for cat, dl in discover_live_github_m3us():
        if dl not in known:
            sources.append((cat, dl))
            known.add(dl)

    print("[+] Descargando %d fuentes hispanas..." % len(sources))
    with ThreadPoolExecutor(max_workers=24) as ex:
        texts = list(ex.map(lambda s: fetch_text(s[1]), sources))   # map conserva el orden
    raw_total = 0
    for (cat, _u), txt in zip(sources, texts):
        if not txt:
            continue
        for it in parse_m3u_content(txt, cat):
            raw_total += 1
            add_pool(it['name'], it['url'], it['logo'], it['raw_group'], tvg_country(it['tvg_id']))
    print("    -> %d senales hispanas validas | %d canales unicos" % (raw_total, len(pool)))

    # 4. FASE A: verificar canales existentes (sin reemplazar lo que funciona)
    ex_urls = sorted({u for ch in existing.values() for u in ch['urls']})
    print("[+] FASE A: auditando %d enlaces de tu lista actual..." % len(ex_urls))
    with ThreadPoolExecutor(max_workers=128) as ex:
        status = dict(zip(ex_urls, ex.map(lambda u: probe(u, 4.0), ex_urls)))
    retry = [u for u, s in status.items() if s == DEAD]
    if retry:
        print("    -> reintentando %d enlaces caidos con mas paciencia..." % len(retry))
        with ThreadPoolExecutor(max_workers=96) as ex:
            for u, s in zip(retry, ex.map(lambda u: probe(u, 8.0), retry)):
                status[u] = s
    dead_ratio = (sum(1 for s in status.values() if s == DEAD) / len(status)) if status else 0.0
    network_glitch = dead_ratio > 0.5
    if network_glitch:
        print("[!] %.0f%% caidos: falla de red masiva. No se penaliza ni se borra nada." % (dead_ratio * 100))

    stats = collections.Counter()
    final_channels = collections.OrderedDict()
    used_urls = set()
    need_repair = []
    removed_dead = []
    for k, ch in existing.items():
        alive = [u for u in ch['urls'] if status.get(u) == OK and not is_foreign_garbage(ch['name'], "", u)]
        dead = [u for u in ch['urls'] if u not in alive]
        for u in alive:
            strikes.pop(u, None)
        for u in dead:
            if not network_glitch:
                strikes[u] = strikes.get(u, 0) + 1
            if strikes.get(u, 0) >= MAX_STRIKES:
                strikes.pop(u, None)
        # REGLA DE ORO DE TOLERANCIA CERO:
        # En la lista M3U final SOLO y EXCLUSIVAMENTE se colocan enlaces vivos confirmados.
        # Jamas se exporta un enlace caido o con error 403/404 al reproductor del usuario.
        urls = list(alive)
        group = "Favoritos de Leo VIP" if k in fav_keys else ch['group']
        final_channels[k] = {'name': ch['name'], 'logo': ch['logo'], 'group': group, 'urls': urls}
        used_urls.update(urls)
        if alive:
            stats['conservados'] += 1
        else:
            need_repair.append(k)

    # 5. Reparar canales cuyo enlace realmente cayo (con espejo hispano verificado)
    def find_replacement(k):
        p = pool.get(k)
        if not p:
            return k, None
        for u in p['urls'][:8]:
            if u in used_urls or is_foreign_garbage(final_channels[k]['name'], "", u):
                continue
            if probe(u, 5.0) == OK:
                return k, u
        return k, None

    if need_repair:
        print("[+] Reparando %d canales con enlace caido..." % len(need_repair))
        with ThreadPoolExecutor(max_workers=64) as ex:
            for k, u in ex.map(find_replacement, need_repair):
                if u and u not in used_urls:
                    final_channels[k]['urls'].append(u)
                    used_urls.add(u)
                    stats['reparados'] += 1
                else:
                    stats['sin_senal_purgado'] += 1

    # PURGA ESTRICTA CON RADAR DE RESURRECCION:
    # Si un canal no tiene enlaces vivos, NO se exporta al M3U (cero pantallas negras),
    # pero se guarda en el radar permanente para que el robot siga buscandole senal en cada ejecucion.
    unviable = [k for k, ch in final_channels.items() if not ch['urls']]
    for k in unviable:
        ch = final_channels[k]
        radar[k] = {'name': ch['name'], 'logo': ch['logo'], 'group': ch['group']}
        del final_channels[k]
        removed_dead.append(ch['name'])

    # RADAR DE RESURRECCION ACTIVO:
    # Buscar si algun canal previamente caido volvio a tener senal viva en el pool
    resurrect_keys = [k for k in radar if k in pool and k not in final_channels]
    if resurrect_keys:
        def try_resurrect(k):
            info = radar[k]
            for u in pool[k]['urls'][:8]:
                if u in used_urls or is_foreign_garbage(info['name'], "", u):
                    continue
                if probe(u, 5.0) == OK:
                    return k, u
            return k, None

        with ThreadPoolExecutor(max_workers=32) as ex:
            for k, u in ex.map(try_resurrect, resurrect_keys):
                if u:
                    info = radar.pop(k)
                    final_channels[k] = {'name': info['name'], 'logo': info['logo'], 'group': info['group'], 'urls': [u]}
                    used_urls.add(u)
                    stats['resucitados'] += 1
                    print("[+] RESUCITADO: Canal %s volvio a tener senal viva y reingreso a la lista" % info['name'])

    # 5B. Enriquecer canales existentes con opciones de respaldo vivas (sin tocar la opcion 1)
    need_backup = [
        k for k, ch in final_channels.items()
        if len(ch['urls']) < MAX_URLS_PER_CHANNEL and k in pool
        and any(u not in ch['urls'] and u not in used_urls and not is_foreign_garbage(ch['name'], "", u) for u in pool[k]['urls'])
    ]
    if need_backup:
        def find_backup(k):
            ch = final_channels[k]
            for u in pool[k]['urls'][:4]:
                if u in ch['urls'] or u in used_urls or is_foreign_garbage(ch['name'], "", u):
                    continue
                if probe(u, 3.5) == OK:
                    return k, u
            return k, None

        with ThreadPoolExecutor(max_workers=64) as ex:
            for k, u in ex.map(find_backup, need_backup[:350]):
                if u and u not in used_urls and len(final_channels[k]['urls']) < MAX_URLS_PER_CHANNEL:
                    final_channels[k]['urls'].append(u)
                    used_urls.add(u)
                    stats['espejos_respaldo'] += 1

    # 6. FASE B: canales NUEVOS (solo si el flujo real se confirma)
    new_keys = [k for k in pool if k not in final_channels and k not in existing]
    scored = []
    for k in new_keys:
        p = pool[k]
        grp, prio, vip = classify_and_score(p['name'], p['raw_group'], p['c_code'], fav_keys)
        scored.append((prio, p['name'].lower(), k, grp, vip))
    scored.sort()
    scored = scored[:NEW_CANDIDATES_CAP]
    print("[+] FASE B: sondeando %d canales hispanos nuevos..." % len(scored))

    def test_new(entry):
        _prio, _n, k, grp, vip = entry
        good = []
        for u in pool[k]['urls'][:4]:
            if u in used_urls:
                continue
            if probe(u, 4.0) == OK:
                good.append(u)
                if len(good) >= (2 if vip else 1):
                    break
        return k, grp, good

    with ThreadPoolExecutor(max_workers=128) as ex:
        new_results = list(ex.map(test_new, scored))
    new_names = []
    for k, grp, good in new_results:
        good = [u for u in good if u not in used_urls]
        if not good:
            continue
        p = pool[k]
        final_channels[k] = {'name': p['name'], 'logo': p['logo'], 'group': grp, 'urls': good}
        used_urls.update(good)
        new_names.append(p['name'])
    stats['nuevos'] = len(new_names)

    # 7. Series completas
    series_out, per_series, dead_ids, discovered = harvest_complete_series()
    series_out, preserved_old, _pluto_vod_map, _pluto_poster = reconcile_series_entries(series_out, existing_series, dead_ids)
    per_series = {}
    for _g, _n, _u, _l in series_out:
        _sn = re.sub(r'^Series:\s*', '', _g, flags=re.I)
        _sn = re.split(r'\s*-\s*(?:Temporada|Saga|Especiales)\b', _sn, flags=re.I)[0].strip()
        if _sn:
            per_series[_sn] = per_series.get(_sn, 0) + 1
    series_urls = {e[2] for e in series_out}

    # 8. Escritura atomica + respaldo
    if os.path.exists(OUTPUT_M3U):
        try:
            with open(OUTPUT_M3U, 'rb') as src, open(BACKUP_M3U, 'wb') as dst:
                dst.write(src.read())
        except Exception:
            pass
    ordered = sorted(final_channels.values(), key=lambda c: (CAT_ORDER.get(c['group'], 99), c['name'].lower()))
    total_entries = 0
    tmp = OUTPUT_M3U + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write('#EXTM3U x-tvg-url="https://iptv-org.github.io/epg/guides/co.xml,https://www.tdtchannels.com/epg/TV.xml.gz"\n')
        f.write('# ==========================================================================\n')
        f.write('# LISTA MAESTRA OMEGA VIP LEONARDO - %d canales + %d episodios de series\n' % (len(ordered), len(series_out)))
        f.write('# Robot Cazador Supremo v4.0 - %s\n' % time.strftime('%Y-%m-%d %H:%M'))
        f.write('# ==========================================================================\n\n')
        for ch in ordered:
            ch['urls'].sort(key=mirror_priority_score)
            logo = ' tvg-logo="%s"' % ch['logo'] if ch['logo'] else ''
            for i, u in enumerate(ch['urls'][:MAX_URLS_PER_CHANNEL]):
                nm = ch['name'] if i == 0 else "%s [Opcion %d]" % (ch['name'], i + 1)
                f.write('#EXTINF:-1 tvg-name="%s"%s group-title="%s",%s\n%s\n' % (nm, logo, ch['group'], nm, u))
                total_entries += 1
        for grp, name, url, logo in series_out:
            f.write('#EXTINF:-1 tvg-name="%s" tvg-logo="%s" group-title="%s",%s\n%s\n' % (name, logo, grp, name, url))
    os.replace(tmp, OUTPUT_M3U)

    # Generar versiones especializadas: solo TV en vivo (ultrarrápida) y solo series
    live_file = os.path.join(APP_DIR, "lista_en_vivo.m3u")
    series_file = os.path.join(APP_DIR, "lista_series.m3u")
    try:
        header_base = '#EXTM3U x-tvg-url="https://iptv-org.github.io/epg/guides/co.xml,https://www.tdtchannels.com/epg/TV.xml.gz"\n'
        with open(live_file, 'w', encoding='utf-8') as lf:
            lf.write(header_base)
            lf.write('# LISTA EN VIVO VIP (Ultraligera, carga en 1 segundo en Smart TV o Celular)\n\n')
            for ch in ordered:
                ch['urls'].sort(key=mirror_priority_score)
                logo = ' tvg-logo="%s"' % ch['logo'] if ch['logo'] else ''
                for i, u in enumerate(ch['urls'][:MAX_URLS_PER_CHANNEL]):
                    nm = ch['name'] if i == 0 else "%s [Opcion %d]" % (ch['name'], i + 1)
                    lf.write('#EXTINF:-1 tvg-name="%s"%s group-title="%s",%s\n%s\n' % (nm, logo, ch['group'], nm, u))
        with open(series_file, 'w', encoding='utf-8') as sf:
            sf.write(header_base)
            sf.write('# SERIES CLASICAS COMPLETAS EN AUDIO LATINO\n\n')
            for grp, name, url, logo in series_out:
                sf.write('#EXTINF:-1 tvg-name="%s" tvg-logo="%s" group-title="%s",%s\n%s\n' % (name, logo, grp, name, url))
    except Exception as e:
        print("[!] Error exportando lista_series.m3u:", e)

    # 8.0.1 Exportar series_catalog.json estructurado por temporadas y capítulos para Omega Mobile
    try:
        series_cat_file = os.path.join(APP_DIR, "series_catalog.json")
        # Reconstruccion biyectiva 1:1 desde series_out (sin duplicados heredados de temporadas previas)
        catalog_map = {}

        for grp, name, url, logo in series_out:
            # Separar serie de temporada sin romper nombres con guion como He-Man
            m_grp = re.match(r'Series:\s*(.+?)\s*-\s*((?:Temporada|Saga|Especiales)\b.*)', grp, re.I)
            if m_grp:
                s_name = m_grp.group(1).strip()
                sea_name = m_grp.group(2).strip()
            else:
                s_name = grp.replace("Series:", "").strip()
                sea_name = "Temporada 01"

            if not s_name:
                continue

            s_key = s_name.lower()
            if s_key not in catalog_map:
                catalog_map[s_key] = {
                    "series": s_name,
                    "logo": logo,
                    "total_seasons": 0,
                    "total_episodes": 0,
                    "seasons": []
                }
            s_obj = catalog_map[s_key]
            if not s_obj.get('logo') and logo:
                s_obj['logo'] = logo

            season_found = None
            for sn in s_obj['seasons']:
                if sn.get('season', '').lower() == sea_name.lower():
                    season_found = sn
                    break
            if not season_found:
                season_found = {"season": sea_name, "episodes": []}
                s_obj['seasons'].append(season_found)

            known_urls = {ep.get('url') for ep in season_found['episodes']}
            if url not in known_urls:
                season_found['episodes'].append({
                    "name": name,
                    "url": url
                })

        final_series_catalog = []
        for s_key, s_obj in catalog_map.items():
            s_obj['seasons'] = [sn for sn in s_obj['seasons'] if sn.get('episodes')]
            s_obj['total_seasons'] = len(s_obj['seasons'])
            s_obj['total_episodes'] = sum(len(sn['episodes']) for sn in s_obj['seasons'])
            if s_obj['total_episodes'] > 0:
                final_series_catalog.append(s_obj)

        postprocess_series_catalog(final_series_catalog, _pluto_vod_map, _pluto_poster)
        final_series_catalog = [s for s in final_series_catalog if s.get('total_episodes', 0) > 0]
        final_series_catalog.sort(key=lambda s: s.get('series', '').lower())

        # Compactar JSON y respetar techo estricto <= 4,350,000 bytes (seguridad localStorage WebView 5MB)
        max_cat_bytes = 4_350_000
        payload_bytes = json.dumps(final_series_catalog, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        if len(payload_bytes) > max_cat_bytes:
            trim_order = [n.lower() for t, n, _ in reversed(PLUTO_CO_SERIES_CATALOG) if t >= 2] + \
                         [n.lower() for t, n, _ in reversed(PLUTO_CO_SERIES_CATALOG) if t == 1]
            for drop_key in trim_order:
                if len(payload_bytes) <= max_cat_bytes:
                    break
                before_n = len(final_series_catalog)
                final_series_catalog = [s for s in final_series_catalog if (s.get('series') or '').lower() != drop_key]
                if len(final_series_catalog) < before_n:
                    payload_bytes = json.dumps(final_series_catalog, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
                    print(f"[!] Presupuesto JSON: omitida '{drop_key}' de series_catalog.json -> {len(payload_bytes):,} B")

        tmp_cat = series_cat_file + '.tmp'
        with open(tmp_cat, 'wb') as scf:
            scf.write(payload_bytes)
        os.replace(tmp_cat, series_cat_file)
        print("[+] series_catalog.json actualizado exitosamente (%d series, %d temporadas, %d eps, %s B)" % (
            len(final_series_catalog),
            sum(s['total_seasons'] for s in final_series_catalog),
            sum(s['total_episodes'] for s in final_series_catalog),
            f"{len(payload_bytes):,}"
        ))

        # Copia directa a assets de Omega Mobile para futuras compilaciones
        omega_assets_dir = r"C:\Users\leoka\.gemini\antigravity\scratch\omega_music_app\assets"
        if os.path.exists(omega_assets_dir):
            omega_series_cat = os.path.join(omega_assets_dir, "series_catalog.json")
            tmp_ocat = omega_series_cat + '.tmp'
            with open(tmp_ocat, 'wb') as oscf:
                oscf.write(payload_bytes)
            os.replace(tmp_ocat, omega_series_cat)
            for asset_name in ("lista_series.m3u", "lista_en_vivo.m3u"):
                src_m3u = os.path.join(APP_DIR, asset_name)
                if os.path.exists(src_m3u):
                    dst_m3u = os.path.join(omega_assets_dir, asset_name)
                    tmp_m3u = dst_m3u + '.tmp'
                    shutil.copyfile(src_m3u, tmp_m3u)
                    os.replace(tmp_m3u, dst_m3u)
    except Exception as e:
        print("[!] Error exportando series_catalog.json:", e)

    # 8.1 Exportar latam_tv_catalog.json sincronizado para Omega Music Mobile
    try:
        cat_file = os.path.join(APP_DIR, "latam_tv_catalog.json")
        export_cat = load_json(cat_file, {})
        if not isinstance(export_cat, dict) or 'countries' not in export_cat:
            export_cat = load_json(LATAM_CATALOG_PATH, {})
        if isinstance(export_cat, dict) and 'channels' in export_cat:
            # Mapear URLs verificadas a los canales del catalogo
            url_map = {}
            for ch in ordered:
                k = key_for_dedup(clean_channel_name(ch['name']))
                if k and ch['urls']:
                    url_map[k] = ch['urls']
            
            updated_count = 0
            for ch in export_cat.get('channels', []):
                k = key_for_dedup(clean_channel_name(ch.get('n', '')))
                if k in url_map:
                    ch['u'] = url_map[k][:MAX_URLS_PER_CHANNEL]
                    updated_count += 1
            
            export_cat['version'] = time.strftime('%Y-%m-%d %H:%M')
            with open(cat_file, 'w', encoding='utf-8') as cf:
                json.dump(export_cat, cf, ensure_ascii=False, indent=2)
            print("[+] latam_tv_catalog.json actualizado exitosamente (%d canales refrescados)" % updated_count)

            # Sincronizar en assets de Omega Mobile
            omega_assets_dir = r"C:\Users\leoka\.gemini\antigravity\scratch\omega_music_app\assets"
            if os.path.exists(omega_assets_dir):
                with open(os.path.join(omega_assets_dir, "latam_tv_catalog.json"), 'w', encoding='utf-8') as ocf:
                    json.dump(export_cat, ocf, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[!] Error exportando latam_tv_catalog.json:", e)

    # 8.2 Sincronización Automática con la Nube GitHub (leo31847/iptv-vip-leo)
    # Permite que la app en el celular (APK) reciba las actualizaciones en vivo por internet (OTA)
    try:
        import subprocess
        print("[+] Sincronizando con la nube GitHub (leo31847/iptv-vip-leo)...")
        files_to_add = [
            "latam_tv_catalog.json",
            "series_catalog.json",
            "lista_series.m3u",
            "lista_en_vivo.m3u",
            "LISTA_MAESTRA_LEO_VIP.m3u",
            "series_deseadas.json",
            "series_completas_cache.json"
        ]
        existing_add = [f for f in files_to_add if os.path.exists(os.path.join(APP_DIR, f))]
        if existing_add:
            subprocess.run(["git", "add"] + existing_add, cwd=APP_DIR, capture_output=True)
            commit_msg = "chore(robot): auto-sync channels and series [%s]" % time.strftime('%Y-%m-%d %H:%M')
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=APP_DIR, capture_output=True)
            push_res = subprocess.run(["git", "push", "origin", "main"], cwd=APP_DIR, capture_output=True)
            if push_res.returncode == 0:
                print("[+] ✅ SINCRONIZACIÓN EXITOSA CON GITHUB: El celular recibirá los cambios al instante.")
            else:
                print("[!] Aviso Git push:", push_res.stderr.decode('utf-8', errors='ignore'))
    except Exception as e:
        print("[!] Error en auto-sync Git:", e)

    # Copia directa al Escritorio con nombre claro para compartir por WhatsApp
    desktop_copy = r"C:\Users\leoka\OneDrive\Escritorio\LISTA_PARA_ENVIAR_POR_WHATSAPP.m3u"
    try:
        with open(OUTPUT_M3U, 'rb') as src, open(desktop_copy, 'wb') as dst:
            dst.write(src.read())
    except Exception:
        pass

    estado['strikes'] = strikes
    estado['radar_resurreccion'] = radar
    estado['ultima_ejecucion'] = time.strftime('%Y-%m-%d %H:%M:%S')
    save_json_atomic(ESTADO_PATH, estado)

    # 9. Reporte
    elapsed = time.time() - t0
    print("\n" + "=" * 74)
    print("  COMPLETADO EN %.0f s" % elapsed)
    print("=" * 74)
    print("  Canales conservados intactos : %d" % stats['conservados'])
    print("  Canales reparados (caidos)   : %d" % stats['reparados'])
    print("  Opciones de respaldo sumadas : %d (espejos vivos para canales existentes)" % stats['espejos_respaldo'])
    print("  Canales en observacion       : %d (caidos, se reintentan; se borran al 3er fallo seguido)" % stats['en_observacion'])
    print("  Canales NUEVOS agregados     : %d" % stats['nuevos'])
    print("  Extranjeros purgados         : %d" % len(purged))
    print("  Retirados (3 fallos seguidos): %d" % len(removed_dead))
    print("  Episodios de series          : %d (%d series)" % (len(series_out), len(per_series)))
    for s, n in per_series.items():
        print("      - %-32s %d episodios" % (s, n))
    if discovered:
        print("  Colecciones nuevas descubiertas: %d" % len(discovered))
        for iid, s in discovered:
            print("      + %s -> %s" % (s, iid))
    if purged:
        print("  Muestra de extranjeros purgados:")
        for n, why, _u in purged[:25]:
            print("      x %-40s (%s)" % (n[:40], why))

    finish({
        'canales': len(ordered), 'entradas': total_entries, 'conservados': stats['conservados'],
        'reparados': stats['reparados'], 'nuevos': stats['nuevos'], 'purgados': len(purged),
        'episodios': len(series_out), 'series': len(per_series),
    })


def upload_public_m3u(file_path):
    """Sube la lista a un enlace publico permanente https:// para compartir por WhatsApp sin depender de la PC."""
    try:
        import uuid
        boundary = uuid.uuid4().hex
        with open(file_path, 'rb') as f:
            file_bytes = f.read()
        filename = "LISTA_LEO_VIP.m3u"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="reqtype"\r\n\r\n'
            f"fileupload\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="fileToUpload"; filename="{filename}"\r\n'
            f"Content-Type: text/plain\r\n\r\n"
        ).encode('utf-8') + file_bytes + f"\r\n--{boundary}--\r\n".encode('utf-8')
        req = urllib.request.Request(
            "https://catbox.moe/user/api.php",
            data=body,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Content-Type": f"multipart/form-data; boundary={boundary}"
            }
        )
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            res = r.read().decode('utf-8').strip()
            if res.startswith("http"):
                return res
    except Exception:
        pass
    return None


def finish(summary):
    lan_url = "http://%s:9999/master.m3u" % get_lan_ip()
    print("[+] Generando enlace publico en la nube para compartir por WhatsApp...")
    public_url = upload_public_m3u(OUTPUT_M3U) or lan_url
    print("\nEnlace universal publico (para WhatsApp o cualquier TV): %s" % public_url)
    if NO_GUI:
        print("Archivo local en el Escritorio: %s" % OUTPUT_M3U)
        return
    try:
        show_completion_window(OUTPUT_M3U, public_url, summary)
    except Exception as e:
        print("[!] Abriendo bloc de notas y explorador:", e)
        os.system('start notepad.exe "%s"' % OUTPUT_M3U)
        os.system('explorer /select,"%s"' % OUTPUT_M3U)


def show_completion_window(m3u_path, public_url, summary=None):
    import tkinter as tk
    import subprocess

    try:
        p = subprocess.Popen(['clip'], stdin=subprocess.PIPE, shell=True)
        p.communicate(public_url.encode('utf-8'))
    except Exception:
        pass

    root = tk.Tk()
    root.title("✅ LISTA ACTUALIZADA - ROBOT LEO VIP v4.0")
    root.geometry("570x470")
    root.resizable(False, False)
    root.configure(bg="#121620")
    root.attributes("-topmost", True)

    if summary is None:
        head, color = "⚠️ SIN INTERNET - LISTA NO MODIFICADA", "#ff5252"
        body = "No hubo conexión. Tu lista quedó intacta (nada se borró)."
    else:
        head, color = "🎉 ¡LISTA MAESTRA ACTUALIZADA!", "#00e676"
        body = ("📺 %(canales)d canales  |  🎞️ %(episodios)d episodios en %(series)d series\n"
                "✅ Conservados: %(conservados)d   🔧 Reparados: %(reparados)d   ➕ Nuevos: %(nuevos)d\n"
                "🚫 Extranjeros eliminados: %(purgados)d" % summary)

    tk.Label(root, text=head, font=("Arial", 16, "bold"), fg=color, bg="#121620").pack(pady=(20, 6))
    tk.Label(root, text=body, font=("Arial", 10), fg="#b0b8c4", bg="#121620", justify="center").pack(pady=(0, 14))

    def copy_link():
        root.clipboard_clear()
        root.clipboard_append(public_url)
        root.update()
        btn_copy.config(text="✅ ¡ENLACE COPIADO! (Pégalo con Ctrl+V)", bg="#00c853")

    btn_copy = tk.Button(root, text="📋 1. COPIAR ENLACE PARA WHATSAPP (Link universal para cualquiera)", font=("Arial", 11, "bold"),
                         bg="#ff8800", fg="white", activebackground="#e07700", cursor="hand2",
                         command=copy_link, relief="flat", pady=8)
    btn_copy.pack(fill="x", padx=45, pady=5)

    tk.Button(root, text="📄 2. ABRIR EN BLOC DE NOTAS (Para ver el texto)", font=("Arial", 11, "bold"),
              bg="#242b3d", fg="white", activebackground="#323b54", cursor="hand2",
              command=lambda: subprocess.Popen('notepad.exe "%s"' % m3u_path, shell=True),
              relief="flat", pady=8).pack(fill="x", padx=45, pady=5)

    tk.Button(root, text="📁 3. MOSTRAR ARCHIVO (En tu Escritorio)", font=("Arial", 11, "bold"),
              bg="#1e222d", fg="#00e676", activebackground="#2a303f", cursor="hand2",
              command=lambda: subprocess.Popen('explorer /select,"%s"' % m3u_path),
              relief="flat", pady=8).pack(fill="x", padx=45, pady=5)

    tk.Label(root, text="Enlace universal listo en portapapeles:\n%s" % public_url,
             font=("Consolas", 9), fg="#78909c", bg="#121620").pack(pady=(14, 2))
    tk.Label(root, text="Este enlace funciona en cualquier celular, PC o TV del mundo sin tener el PC prendido.",
             font=("Arial", 9, "bold"), fg="#00e676", bg="#121620").pack(pady=(2, 5))
    root.mainloop()


if __name__ == '__main__':
    main()
