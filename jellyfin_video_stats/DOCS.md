# Jellyfin Video Stats

Add-on'et følger med i, hvad der bliver afspillet på din Jellyfin-server, og viser statistik over film og serier.

## Opsætning

1. Opret en API-nøgle i Jellyfin under **Kontrolpanel → API-nøgler → +**.
2. Sæt `jellyfin_url` og `api_key` under add-on'ets **Konfiguration** og start add-on'et.
3. Åbn **Videostatistik** i sidemenuen.

Prikken ved titlen viser forbindelsen: grøn betyder forbundet, rød betyder fejl (hold musen over den for at se detaljer), og grå betyder, at opsamlingen ikke er sat op.

### Jellyfin URL

Kører Jellyfin som add-on på samme maskine, kan du bruge Home Assistants IP-adresse med port 8096, fx `http://192.168.1.10:8096`, eller add-on'ets interne værtsnavn fra Jellyfin-add-on'ets infoside (*Hostname*), fx `http://2937404c-jellyfin:8096`.

## Indstillinger

| Indstilling | Betydning |
|---|---|
| `poll_interval` | Antal sekunder mellem hvert tjek af, hvad der afspilles (3–60). |
| `min_watch_percent` | Hvor stor en del af en film eller et afsnit der skal ses, før det tæller som set. 30 minutter tæller altid, så en lang film ikke kræver over en time. |
| `video_folders` | Mapper med hentede YouTube-videoer eller lignende, standard `Youtube`. Film, hvis sti indeholder en mappe med det navn, tælles som videoer og grupperes efter kanal i stedet for at fylde i "Top film". Store og små bogstaver er ligegyldige. |
| `ha_sensors` | Opretter sensorer i Home Assistant med seetid, hvad der afspilles, transcodinger og serier i gang (standard: til). |
| `notify_new_episodes` | Giver besked, når en serie, du følger, får nye afsnit (standard: til). |
| `notify_service` | Valgfri. Fx `notify.mobile_app_din_telefon`. Tom betyder en besked under Notifikationer i Home Assistant. |
| `user_map` | Valgfri. Kobler Home Assistant-brugere til Jellyfin-brugere, når navnene er forskellige. Én linje pr. bruger, fx `christian=Tntdruid`. |

## Hvad tæller hvordan?

- **Afspilninger under ét minut** gemmes slet ikke (trailere, fejlklik og kig).
- **Set**: nok af filmen eller afsnittet er set (`min_watch_percent`, højst 30 minutter). Kortere afspilninger vises som "kun kigget".
- **Set færdig**: afspilningen nåede mindst 90 % af vejen, dvs. typisk til rulleteksterne.
- **Seetid** er den tid, der faktisk er afspillet. Pauser tæller ikke med, og spoling forvirrer ikke tallet.
- **Binge** er flest afsnit af samme serie, som én bruger har set på én dag.
- **Transcoding** registreres, hvis Jellyfin på noget tidspunkt under afspilningen transcodede videoen. Fanen **Afspilning** viser, hvilke klienter der transcoder, og hvorfor.

## Home Assistant: sensorer og besked om nye afsnit

Add-on'et taler selv med Home Assistant, så der skal ikke sættes noget op. Status og en liste over sensorerne finder du nederst på fanen **Afspilning**.

### Sensorer

| Sensor | Værdi | Attributter |
|---|---|---|
| `sensor.jellyfin_video_stats_watch_time_today` | Minutter set i dag, alle brugere | `per_user` |
| `sensor.jellyfin_video_stats_watch_time_today_<bruger>` | Minutter set i dag af én bruger, fx `…_today_christian` | |
| `sensor.jellyfin_video_stats_watch_time_week` | Minutter set denne uge (fra mandag) | `per_user` |
| `sensor.jellyfin_video_stats_now_playing` | Antal afspilninger lige nu | `sessions` (bruger, enhed, titel, pause, transcoding, procent), `titles` |
| `sensor.jellyfin_video_stats_transcoding` | Antal afspilninger, der transcodes lige nu | `sessions` |
| `sensor.jellyfin_video_stats_continue_watching` | Antal serier i gang | `series` (næste afsnit, set/i alt, minutter tilbage) |
| `sensor.jellyfin_video_stats_last_watched` | Det senest sete | `user`, `watched_at` |

Seetiden tæller også det, der afspilles lige nu, så den kan bruges til grænser for skærmtid. Sensorerne opdateres hvert halve minut. De er almindelige tilstande, ikke enheder med et unikt id, så de kan ikke omdøbes i Home Assistant. Vil du have et andet navn, kan du lave en template-sensor. Slå dem fra med `ha_sensors: false`.

### Besked om nye afsnit

Hver halve time tjekker add-on'et, om der er kommet nye afsnit i Jellyfin. Hører afsnittet til en serie, nogen følger, sender det en besked. Man følger en serie, hvis man har set alle tidligere afsnit, eller hvis man har set i den inden for de sidste 60 dage.

- Uden `notify_service` kommer beskeden under **Notifikationer** i Home Assistant.
- Med fx `notify_service: notify.mobile_app_din_telefon` kommer den på telefonen.
- Samtidig sendes eventet `jellyfin_video_stats_new_episode` med `series`, `series_id`, `episodes` (fx `S04E01` og navn) og `users`, så du kan bygge dine egne automationer.
- Første gang add-on'et starter, sendes der ikke besked om afsnit, der allerede ligger i Jellyfin.

Slå det fra med `notify_new_episodes: false`.

### Eksempler

Besked på telefonen, når børnene har set mere end to timer i dag:

```yaml
automation:
  - alias: "Skærmtid: to timer"
    trigger:
      - platform: numeric_state
        entity_id: sensor.jellyfin_video_stats_watch_time_today_gaest
        above: 120
    action:
      - service: notify.mobile_app_din_telefon
        data:
          message: "Gæst har set {{ states('sensor.jellyfin_video_stats_watch_time_today_gaest') }} minutter i dag."
```

Send kun besked om nye afsnit til den person, der følger serien (sæt `notify_new_episodes` til, og lad `notify_service` stå tom, hvis I ikke også vil have den fælles besked):

```yaml
automation:
  - alias: "Nye afsnit til Christian"
    trigger:
      - platform: event
        event_type: jellyfin_video_stats_new_episode
    condition:
      - "{{ 'Christian' in trigger.event.data.users }}"
    action:
      - service: notify.mobile_app_christians_telefon
        data:
          title: "Nyt i {{ trigger.event.data.series }}"
          message: "{{ trigger.event.data.episodes | map(attribute='episode') | join(', ') }} er klar."
```

## Fremdrift i serier

Add-on'et henter hele afsnitslisten for de serier, der er set i, så det kan vise, hvor langt du er:

- **Fortsæt med at se** på oversigten: serier i gang med næste afsnit, hvor mange der er tilbage, og hvor lang tid det tager.
- **Gjort færdig**: serier, hvor alle afsnit er set. Fortsætter serien i Jellyfin, står der "Ajour – venter på nye afsnit".
- **Seriesiden**: fremdrift i procent, en bjælke pr. sæson og alle afsnit, også dem du ikke har set endnu (vises nedtonet).
- **Wrapped** viser, hvilke serier du har set færdige i løbet af året.

Et afsnit tæller som set, hvis add-on'et har registreret det, eller hvis det er markeret som set i Jellyfin. Så tæller afsnit, du så før add-on'et, eller som du selv har markeret, også med. Specials (sæson 0) og afsnit, der mangler i biblioteket, tælles ikke. Listerne opdateres hver 12. time og kort efter, at et afsnit er set. Fremdriften viser, hvordan det står lige nu, og afhænger ikke af den valgte periode.

## Gammel historik fra Playback Reporting

Bruger du Jellyfins **Playback Reporting**-plugin, har det logget dine afspilninger, siden det blev installeret. Første gang add-on'et starter, henter det automatisk den historik, så statistikken også dækker tiden før add-on'et. Du kan se status og importere igen under fanen **Afspilning** nederst.

- Det er sikkert at importere igen, fx efter add-on'et har været stoppet. Afspilninger, der allerede er registreret (samme bruger og titel med start inden for 15 minutter), springes over.
- Pluginet ved ikke, hvor langt man nåede i en film. "Set færdig" bliver derfor anslået ud fra den tid, der er set.
- Pluginet logger ikke opløsning, sprog eller årsager til transcoding, så de tal dækker kun tiden efter add-on'et.
- Film og afsnit, der er slettet fra Jellyfin siden, kommer med under det navn, pluginet har gemt. For afsnit genskabes serie, sæson og afsnitsnummer.
- Har du ikke pluginet, sker der ingenting. Det kan installeres under **Kontrolpanel → Plugins → Katalog**, men det har kun historik fra det tidspunkt, det blev installeret.

## YouTube og andre videoer

Jellyfin kan ikke selv afspille YouTube, men videoer, du har hentet ned (fx med ytdl-sub, TubeArchivist eller yt-dlp), tælles med:

- **Bibliotek af typen Film:** Jellyfin ser videoerne som film. Ligger de under en mappe nævnt i `video_folders` (standard `Youtube`, fx `/mnt/Youtube/Buy it Fix it/…`), tælles de som **videoer** i stedet. Ellers tælles de som film.
- **Bibliotek af typen Hjemmevideoer eller Blandet indhold, eller via et kanal-plugin:** videoerne tælles altid som **videoer**.
- **Bibliotek af typen Serier** (fx ytdl-sub sat op som serier): hver kanal bliver en serie.

Videoer grupperes efter **kanal**. Du får så "Top kanaler" og "Top videoer" på oversigten og en side for hver kanal. Kanalen findes i denne rækkefølge:

1. Kanalen fra Jellyfins kanal-plugin
2. `<studio>` i videoens .nfo-fil, som yt-dlp/ytdl-sub udfylder med kanalnavnet
3. Den mappe, videoen ligger i (de fleste downloadere laver én mappe pr. kanal)
4. Biblioteket

## Billeder

Plakater, thumbnails og portrætter gemmes lokalt i mappen `images/` ved siden af databasen, første gang de bruges. Det sker allerede, når noget bliver afspillet. Hvis en film, serie eller video senere slettes fra Jellyfin, vises billedet stadig i statistikken. Billederne hentes igen efter 30 dage, så ændret artwork bliver opdateret, men den gamle kopi beholdes, hvis Jellyfin ikke længere har billedet. Mappen kommer med i Home Assistants backups. Den fylder typisk 20–40 KB pr. billede.

## Flere brugere

Når du åbner Videostatistik, viser siden automatisk **din egen** statistik. Det sker, hvis dit brugernavn eller visningsnavn i Home Assistant er det samme som dit brugernavn i Jellyfin (store og små bogstaver er ligegyldige). I brugermenuen står der "(dig)" ved dig, og du kan altid skifte til "Alle brugere", en anden bruger eller fanen Sammenlign.

Hvis navnene er forskellige, kobler du dem under `user_map`.

## Bemærk

- Jellyfin gemmer ikke selv en afspilningshistorik. Uden Playback Reporting-pluginet starter statistikken derfor først, når add-on'et kører.
- Film, serieafsnit og videoer tælles med. Musik, musikvideoer og live-tv ignoreres.
- Data gemmes i SQLite-filen `video_stats.db` i add-on'ets offentlige config-mappe. Via Samba ligger den under `app_configs/<id>_jellyfin_video_stats/` (`addon_configs` på ældre Home Assistant). Filen kommer med i Home Assistants backups.
