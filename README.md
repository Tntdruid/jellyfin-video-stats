<p align="center"><img src="assets/logo.png" width="160" alt="Jellyfin Video Stats logo"></p>

<h1 align="center">Jellyfin Video Stats</h1>

<p align="center"><a href="https://github.com/Tntdruid/jellyfin-video-stats/actions/workflows/ci.yaml"><img src="https://github.com/Tntdruid/jellyfin-video-stats/actions/workflows/ci.yaml/badge.svg" alt="CI"></a></p>

🇬🇧 [English](#english) · 🇩🇰 [Dansk](#dansk)

---

## English

A Home Assistant add-on with viewing statistics for movies, series and videos in Jellyfin. It is the video sibling of [Jellyfin Music Stats](https://github.com/Tntdruid/jellyfin-music-stats). The add-on's own pages are in Danish.

- Imports old history from the Playback Reporting plugin, so the statistics don't start from zero
- Watch time per day, week and month, split into movies, series and videos and compared with the previous period
- Series progress: "continue watching" with the next episode, finished series and progress per season
- Home Assistant sensors (watch time today per user, now playing, transcodes, series in progress) and notifications when a series you follow gets new episodes
- Top series, movies and actors with posters, which are stored locally and survive the file being deleted
- YouTube and other videos grouped by channel, also when Jellyfin sees them as movies
- Genres over time and a heatmap of when you watch
- Smarter numbers: binges, share watched to the end, streaks, new series, rewatched movies, forgotten series and automatic insights
- Live "now playing" with resolution and transcoding
- Pages for series (episode by episode), movies (cast), actors and channels
- Playback: direct play versus transcoding, which clients transcode and why, resolution, audio and subtitle languages
- Wrapped: a yearly summary with viewer type, series of the year, top 5 lists and fun facts
- User comparison with a taste match and shared titles
- CSV export of plays (opens directly in Danish Excel)
- Multiple users

See [jellyfin_video_stats/DOCS.md](jellyfin_video_stats/DOCS.md) for setup (in Danish).

### Installation in Home Assistant

1. Go to **Settings → Apps → App store → ⋮ → Repositories**.
2. Add `https://github.com/Tntdruid/jellyfin-video-stats`.
3. Find **Jellyfin Video Stats** in the store and install it.
4. Under **Configuration**, set `jellyfin_url` and `api_key` (create the key in Jellyfin under **Dashboard → API Keys**), then start the add-on.
5. Open **Videostatistik** in the sidebar.

Home Assistant builds the add-on on your machine, so the first installation takes a few minutes.

**Updates:** raise `version` in `jellyfin_video_stats/config.yaml` and push. Home Assistant then shows the update in the store.

### Local development with demo data

```bash
python -m venv .venv
.venv/Scripts/pip install -r jellyfin_video_stats/app/requirements.txt
curl -L -o jellyfin_video_stats/app/static/echarts.min.js https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js
.venv/Scripts/python dev/seed_demo.py
.venv/Scripts/python dev/run_demo.py
```

Then open http://localhost:8099. If you set `JELLYFIN_URL` and `API_KEY` as environment variables, the local copy also collects real data.

Run the tests with:

```bash
.venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest tests
```

On every push, GitHub Actions runs the tests and checks the add-on configuration. The image is built and started for both amd64 and aarch64, so a broken version is caught before Home Assistant tries to install it.

---

## Dansk

Home Assistant-add-on med seerstatistik for film, serier og videoer i Jellyfin. Det er video-søsteren til [Jellyfin Music Stats](https://github.com/Tntdruid/jellyfin-music-stats).

- Henter gammel historik fra Playback Reporting-pluginet, så statistikken ikke starter fra nul
- Seetid pr. dag, uge og måned, delt op i film, serier og videoer og sammenlignet med forrige periode
- Fremdrift i serier: "Fortsæt med at se" med næste afsnit, serier gjort færdige og fremdrift pr. sæson
- Sensorer i Home Assistant (seetid i dag pr. bruger, afspilles nu, transcodinger, serier i gang) og besked, når en serie, du følger, får nye afsnit
- Top serier, film og skuespillere med plakater, der gemmes lokalt og overlever, at filen slettes
- YouTube- og andre videoer grupperet efter kanal, også når Jellyfin ser dem som film
- Genrer over tid og heatmap over, hvornår du ser
- Smartere tal: binge, andel set færdig, streaks, nye serier, gensete film, glemte serier og automatiske indsigter
- Live "afspilles nu" med opløsning og transcoding
- Sider for serier (afsnit for afsnit), film (medvirkende), skuespillere og kanaler
- Afspilning: direkte afspilning mod transcoding, hvilke klienter der transcoder og hvorfor, opløsning, lyd- og undertekstsprog
- Wrapped: årsoversigt med seertype, årets serie, top 5-lister og sjove fakta
- Sammenligning af brugere med smags-match og fælles titler
- Eksport af afspilninger til CSV (åbner direkte i dansk Excel)
- Understøtter flere brugere

Se [jellyfin_video_stats/DOCS.md](jellyfin_video_stats/DOCS.md) for opsætning.

### Installation i Home Assistant

1. Gå til **Indstillinger → Apps → Apps butik → ⋮ → Repositories**.
2. Tilføj `https://github.com/Tntdruid/jellyfin-video-stats`.
3. Find **Jellyfin Video Stats** i butikken og installér det.
4. Sæt `jellyfin_url` og `api_key` under **Konfiguration** (opret nøglen i Jellyfin under **Kontrolpanel → API-nøgler**), og start add-on'et.
5. Åbn **Videostatistik** i sidemenuen.

Home Assistant bygger add-on'et på din maskine, så den første installation tager et par minutter.

**Opdateringer:** Hæv `version` i `jellyfin_video_stats/config.yaml` og push. Home Assistant viser så opdateringen i butikken.

### Lokal udvikling med demodata

```bash
python -m venv .venv
.venv/Scripts/pip install -r jellyfin_video_stats/app/requirements.txt
curl -L -o jellyfin_video_stats/app/static/echarts.min.js https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js
.venv/Scripts/python dev/seed_demo.py
.venv/Scripts/python dev/run_demo.py
```

Åbn derefter http://localhost:8099. Hvis du sætter `JELLYFIN_URL` og `API_KEY` som miljøvariabler, opsamler den lokale udgave også rigtige data.

Tests køres med:

```bash
.venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest tests
```

Ved hvert push kører GitHub Actions tests og tjekker add-on-konfigurationen. Imaget bygges og startes for både amd64 og aarch64, så en version, der ikke virker, bliver opdaget, før Home Assistant prøver at installere den.

---

<!-- jellyfin-projects:start -->
## More Jellyfin projects / Flere Jellyfin-projekter

| | 🇬🇧 | 🇩🇰 |
|---|---|---|
| [Jellyfin Music Stats](https://github.com/Tntdruid/jellyfin-music-stats) | Home Assistant add-on with music listening stats: top lists, genres, moods, Wrapped | Home Assistant-add-on med lyttestatistik for musik: top-lister, genrer, humør, Wrapped |
| [Episode Title Fixer](https://github.com/Tntdruid/jellyfin-plugin-episode-title-fixer) | Jellyfin plugin that replaces placeholder episode titles like "Episode 11" with the original title | Jellyfin-plugin, der erstatter pladsholdere som "Afsnit 11" med afsnittets originale titel |
| [Auto Artist Playlists](https://github.com/Tntdruid/jellyfin-plugin-auto-artist-playlists) | Jellyfin plugin that hearts the songs you listen to and adds them to a playlist per artist | Jellyfin-plugin, der giver hjerte til de sange, du hører, og samler dem i en playliste pr. kunstner |
| [Tonefin](https://github.com/Tntdruid/tonefin) | Windows music player for Jellyfin that always reports what you play, so stats and plugins see every listen | Musikafspiller til Windows til Jellyfin, der altid rapporterer, hvad du spiller, så statistik og plugins ser hver lytning |
| [TvFin](https://github.com/Tntdruid/TvFin) | Minimal Jellyfin player for Samsung Tizen TVs: Quick Connect, resume where you left off, chapters, subtitles, auto-play next episode | Minimal Jellyfin-afspiller til Samsung Tizen-TV: Quick Connect, fortsæt hvor du slap, kapitler, undertekster, automatisk næste afsnit |
<!-- jellyfin-projects:end -->
