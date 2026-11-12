# Changelog

🇬🇧 English first, 🇩🇰 dansk nedenunder i hver version.

## 0.4.0

🇬🇧
- Sensors in Home Assistant: watch time today and this week (also per user), now playing, current transcodes, series in progress and last watched. Watch time includes what is playing right now, so it can be used for screen time limits.
- A heads-up about new episodes of series you follow, as a notification in Home Assistant or on your phone via `notify_service`, and as the event `jellyfin_video_stats_new_episode` for your own automations.
- New options: `ha_sensors`, `notify_new_episodes` and `notify_service`. The add-on now needs access to Home Assistant's API (`homeassistant_api`).

🇩🇰
- Sensorer i Home Assistant: seetid i dag og denne uge (også pr. bruger), afspilles nu, transcodinger nu, serier i gang og senest set. Seetiden tæller det, der afspilles lige nu, med, så den kan bruges til grænser for skærmtid.
- Besked om nye afsnit af serier, du følger, som notifikation i Home Assistant eller på telefonen via `notify_service`, og som eventet `jellyfin_video_stats_new_episode` til egne automationer.
- Nye indstillinger: `ha_sensors`, `notify_new_episodes` og `notify_service`. Add-on'et kræver nu adgang til Home Assistants API (`homeassistant_api`).

## 0.3.1

🇬🇧
- Fixed: in 0.3.0, episodes were not saved when watched to the end, because the collector crashed. Movies and videos were not affected.
- Tests, a check of the add-on configuration and an image build for amd64 and aarch64 now run automatically on GitHub on every push.

🇩🇰
- Rettet: i 0.3.0 blev afsnit ikke gemt, når de var set færdige, fordi opsamleren gik ned. Film og videoer var ikke berørt.
- Tests, tjek af add-on-konfigurationen og byg af imaget for amd64 og aarch64 kører nu automatisk på GitHub ved hvert push.

## 0.3.0

🇬🇧
- Series progress: "continue watching" with the next episode and time left, "finished", and progress per season on the series page, which lists every episode, including unwatched ones.
- Episodes marked as watched in Jellyfin count towards progress.
- Wrapped shows the series finished during the year. The insight about forgotten series says how many episodes are left, and skips series that have been finished.

🇩🇰
- Fremdrift i serier: "Fortsæt med at se" med næste afsnit og tid tilbage, "Gjort færdig" og fremdrift pr. sæson på seriesiden, hvor alle afsnit vises, også de usete.
- Afsnit, der er markeret som set i Jellyfin, tæller med i fremdriften.
- Wrapped viser de serier, der er set færdige i løbet af året. Indsigten om glemte serier fortæller, hvor mange afsnit der er tilbage, og springer serier over, der er set færdige.

## 0.2.0

🇬🇧
- Imports old history from Jellyfin's Playback Reporting plugin automatically on first start. Status and "import again" are under the Playback tab. Duplicates are skipped, and deleted movies and episodes are included under their saved name.

🇩🇰
- Importerer gammel historik fra Jellyfins Playback Reporting-plugin automatisk ved første start. Status og "Importér igen" findes under fanen Afspilning. Dubletter springes over, og slettede film og afsnit kommer med under deres gemte navn.

## 0.1.0

🇬🇧
- First version, built on the same foundation as Jellyfin Music Stats.
- Collects movies and series episodes from Jellyfin's sessions, with watch time, how far you got, play method, resolution and language.
- Overview with watch time for movies and series, top series, movies and actors, genres over time, a heatmap and automatic insights.
- Pages for series, movies and actors.
- The Playback tab: direct play versus transcoding, clients, reasons, resolution and language.
- Wrapped, user comparison and CSV export.
- Videos (e.g. downloaded YouTube videos in a home video library) are counted and grouped by channel, with top channels, top videos and a page per channel.
- Movies in a folder listed in `video_folders` (default `Youtube`) count as videos. The channel is taken from `<studio>` in the .nfo file, which yt-dlp fills in.
- Posters and thumbnails are stored locally, so they still show after something is deleted from Jellyfin.

🇩🇰
- Første version, bygget på samme grundlag som Jellyfin Music Stats.
- Opsamling af film og serieafsnit fra Jellyfins sessioner med seetid, hvor langt man nåede, afspilningsmetode, opløsning og sprog.
- Oversigt med seetid for film og serier, top serier, film og skuespillere, genrer over tid, heatmap og automatiske indsigter.
- Sider for serier, film og skuespillere.
- Fanen Afspilning: direkte afspilning mod transcoding, klienter, årsager, opløsning og sprog.
- Wrapped, sammenligning af brugere og CSV-eksport.
- Videoer (fx hentede YouTube-videoer i et hjemmevideo-bibliotek) tælles med og grupperes efter kanal, med top kanaler, top videoer og en side pr. kanal.
- Film i en mappe nævnt i `video_folders` (standard `Youtube`) tælles som videoer. Kanalen tages fra `<studio>` i .nfo-filen, som yt-dlp udfylder.
- Plakater og thumbnails gemmes lokalt, så de stadig vises, når noget er slettet fra Jellyfin.
