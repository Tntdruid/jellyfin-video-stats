# Jellyfin Video Stats

Home Assistant-add-on med seerstatistik for film og serier i Jellyfin. Det er video-søsteren til [Jellyfin Music Stats](https://github.com/Tntdruid/jellyfin-music-stats).

- Henter gammel historik fra Playback Reporting-pluginet, så statistikken ikke starter fra nul
- Seetid pr. dag, uge og måned, delt op i film og serier og sammenlignet med forrige periode
- Top serier, film og skuespillere med plakater, der gemmes lokalt og overlever, at filen slettes
- YouTube- og andre videoer grupperet efter kanal
- Genrer over tid og heatmap over, hvornår du ser
- Smartere tal: binge, andel set færdig, streaks, nye serier, gensete film, glemte serier og automatiske indsigter
- Live "afspilles nu" med opløsning og transcoding
- Sider for serier (afsnit for afsnit), film (medvirkende) og skuespillere
- Afspilning: direkte afspilning mod transcoding, hvilke klienter der transcoder og hvorfor, opløsning, lyd- og undertekstsprog
- Wrapped: årsoversigt med seertype, årets serie, top 5-lister og sjove fakta
- Sammenligning af brugere med smags-match og fælles titler
- Eksport af afspilninger til CSV (åbner direkte i dansk Excel)
- Understøtter flere brugere

Se [jellyfin_video_stats/DOCS.md](jellyfin_video_stats/DOCS.md) for opsætning.

## Installation i Home Assistant

1. Gå til **Indstillinger → Apps → Apps butik → ⋮ → Repositories**.
2. Tilføj `https://github.com/Tntdruid/jellyfin-video-stats`.
3. Find **Jellyfin Video Stats** i butikken og installér det.

Home Assistant bygger add-on'et på din maskine, så den første installation tager et par minutter.

**Opdateringer:** Hæv `version` i `jellyfin_video_stats/config.yaml` og push. Home Assistant viser så opdateringen i butikken.

## Lokal udvikling med demodata

```bash
python -m venv .venv
.venv/Scripts/pip install -r jellyfin_video_stats/app/requirements.txt
curl -L -o jellyfin_video_stats/app/static/echarts.min.js https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js
.venv/Scripts/python dev/seed_demo.py
.venv/Scripts/python dev/run_demo.py
```

Åbn derefter http://localhost:8099. Hvis du sætter `JELLYFIN_URL` og `API_KEY` som miljøvariabler, opsamler den lokale udgave også rigtige data.
