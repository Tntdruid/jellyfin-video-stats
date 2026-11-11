# Changelog

## 0.2.0

- Importerer gammel historik fra Jellyfins Playback Reporting-plugin automatisk ved første start. Status og "Importér igen" findes under fanen Afspilning. Dubletter springes over, og slettede film og afsnit kommer med under deres gemte navn.

## 0.1.0

- Første version, bygget på samme grundlag som Jellyfin Music Stats.
- Opsamling af film og serieafsnit fra Jellyfins sessioner med seetid, hvor langt man nåede, afspilningsmetode, opløsning og sprog.
- Oversigt med seetid for film og serier, top serier, film og skuespillere, genrer over tid, heatmap og automatiske indsigter.
- Sider for serier, film og skuespillere.
- Fanen Afspilning: direkte afspilning mod transcoding, klienter, årsager, opløsning og sprog.
- Wrapped, sammenligning af brugere og CSV-eksport.
- Videoer (fx hentede YouTube-videoer i et hjemmevideo-bibliotek) tælles med og grupperes efter kanal, med top kanaler, top videoer og en side pr. kanal.
- Film i en mappe nævnt i `video_folders` (standard `Youtube`) tælles som videoer. Kanalen tages fra `<studio>` i .nfo-filen, som yt-dlp udfylder.
- Plakater og thumbnails gemmes lokalt, så de stadig vises, når noget er slettet fra Jellyfin.
