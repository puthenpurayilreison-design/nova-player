# NOVA — note di versione

Player universale + streaming 4K da link + download manager + torrent, in un'unica app per Windows 11.

## Novità della 4.6 — l'estetica

- **Home come una piattaforma di streaming**: in alto lo spotlight con i film da riprendere e gli ultimi visti, a rotazione con dissolvenza e un lento movimento dello sfondo; logo del titolo, voto, anno, durata, età consigliata, lingua, 4K, generi e trama. Sotto, righe che scorrono di lato (rotella con Shift o frecce): Continua a guardare, La mia lista, Le tue serie, Film, per lingua (In Malayalam, In Tamil…), per genere, Da rivedere.
- **Locandine vive**: al passaggio del mouse si ingrandiscono con un alone di luce e mostrano voto, anno e genere. Clic = scheda, ▶ o doppio clic = guarda subito.
- **Scheda completa** di ogni film e serie: sfondo grande, locandina, logo, slogan, trama, regia, musiche, voto TMDB, cast con foto, trailer (YouTube), episodi che hai della serie, simili nella tua libreria, info sul file (fonte, audio, qualità, dimensione). Esc o Indietro per tornare.
- **La mia lista**: salva i film da vedere (scheda, tasto destro in Home o in Libreria).
- **Libreria**: una sola locandina per serie, con il numero di episodi.
- **Nuova animazione di avvio**: la stella esplode di luce con scintille e onda, le lettere salgono una a una e un riflesso le attraversa (circa 1,5 s, un clic la salta).
- **Il player non se ne accorge**: le immagini si caricano solo quando servono e restano in memoria; le animazioni continue si fermano da sole quando un film è in riproduzione.
- Per trama, cast, logo e trailer serve la chiave TMDB gratuita (Libreria); senza, la Home usa i fotogrammi dei tuoi video.

## Novità della 4.5

- **TV: il PC fa tutto** (Trasmetti › nome della TV). Il PC legge il film, mette i sottotitoli dentro l'immagine e lo ricomprime al volo con la NVIDIA in uno stream leggero: la TV (es. LG del 2019) deve solo mostrarlo. Parte in pochi secondi.
- **Qualità automatica**: se il Wi-Fi non regge, NOVA lo misura e scende subito alla qualità giusta (1080p → 720p) invece di far scattare il film, e si ricorda la qualità buona per quella TV: la volta dopo parte già da lì. Puoi anche sceglierla tu (Alta, Media, Wi-Fi debole, Wi-Fi molto lento).
- Mentre trasmetti il PC non va in sospensione; il volume uguale tra i film vale anche sulla TV. "Ferma la TV" → sul PC riprendi da dove era arrivata la TV.
- Resta anche la modalità **originale** (file così com'è, per il Wi-Fi forte).
- Sottotitoli sulla TV: i file .srt/.ass, quelli dentro i file sul PC e quelli Blu-ray (PGS). Per i film da link con i sottotitoli dentro il file non si può (servirebbe scaricare tutto il film): scaricalo prima o carica un .srt.

## Novità della 4.4 (versione definitiva)

- **Pulsante Aggiorna** in alto, accanto a NOVA, e **F5**: ricarica la scheda aperta. Player: riapre il video dallo stesso punto (utile se uno stream si è piantato). Download: riprova quelli in errore. Torrent: cerca subito nuovi peer. Libreria: ricerca di nuovo i poster mancanti.
- **Cinema in cuffia 3D**: ogni canale del 5.1/7.1 diventa un altoparlante virtuale intorno alla testa (davanti, ai lati, dietro), con ritardo e "ombra" tra le orecchie come dal vero e un po' di stanza: il suono esce dalla testa invece di stare dentro. Funziona anche con lo stereo.
- **Ctrl+F: cerca nei sottotitoli**. Scrivi una frase («treasure bridge»), scegli il risultato e il film salta lì. Funziona con i .srt/.ass esterni e con quelli dentro i file MKV/MP4 sul PC (anche il tasto destro › Sottotitoli › Cerca una frase).
- **Ripresa intelligente**: riparte qualche secondo prima di dove eri (3 s dopo una pausa corta, fino a 25 s se sono passati giorni), così ritrovi il filo.
- **Volume uguale tra i film**: NOVA misura il volume di ogni film (EBU R128) e lo porta allo stesso livello, piano e senza salti; il valore resta salvato per ogni film.
- **Versione per telefono molto più veloce**: con la scheda NVIDIA ora decodifica, ridimensiona e converte tutto sulla GPU; l'HDR viene convertito dopo aver rimpicciolito il video (anche senza GPU è circa 3-4 volte più veloce). Gira a priorità bassa: il PC e i poster restano fluidi. Vedi percentuale, velocità e tempo rimanente, e puoi annullare. Se un metodo non va sul tuo PC passa da solo al successivo.
- **Player più veloce ad aprire**: il motore video si prepara in silenzio all'avvio, il primo film parte subito. Letture di rete più grandi per i link veloci.
- **Download video più veloci** (YouTube e siti con yt-dlp): 16 pezzi in parallelo e richieste a blocchi. yt-dlp si aggiorna da solo ogni 3 giorni.
- **Componenti sempre all'ultima versione**: `crea_exe.bat` scarica ogni volta le ultime versioni di mpv, ffmpeg, aria2 e yt-dlp e aggiorna le librerie.
- **Tolti gli ZIP e le serie in ZIP** (non erano affidabili): le cartelle normali e i file video funzionano come sempre.
- Corretti piccoli errori della Home e della Libreria quando si aggiornavano mentre un'animazione era in corso.

## Novità della 4.1 – 4.3

- Il motore video viene sempre trovato anche nell'exe; se manca un componente NOVA lo riscarica da sola.
- Errori di riproduzione spiegati (link scaduto, server che non permette lo streaming…).

## Novità della 4.0

- **Profilo audio «Cinema indiano»**: voci sempre chiare sopra BGM e canzoni, bassi pieni.
- **Meno buffering**: cache di 2 GB e 3 minuti di pre-lettura con 16 GB di RAM (regge i cali del Wi-Fi), ripartenza con 1,5 s pronti per non ri-fermarsi subito.
- **Wi-Fi in modalità streaming** mentre guardi: niente scansioni in background che ogni minuto bloccano la connessione.
- **Priorità a NOVA** mentre il film è in play.
- **Timer spegnimento** (tasto destro): 15-120 minuti o a fine film, anche con sospensione del PC.
- **Cuffie scollegate = pausa**, invece di far partire il film dalle casse. Quando le ricolleghi torna su di loro.
- NOVA si ricorda **posizione e dimensione della finestra**.

## Novità della 3.0

- **Buffering molto più raro sui link**: se una delle connessioni dello Stream Turbo si pianta (succede con R2/CDN), viene chiusa dopo 2-3 secondi e il pezzo riparte da un'altra. Prima si aspettavano fino a 20 secondi.
- **Sincronizza sottotitoli** e **Salta intro** restano. Tolti i sottotitoli generati con l'AI.

## Novità della 2.2

**Audio**
- **Suono**: Automatico, Originale, Cinema in cuffia, Dialoghi chiari, Volume notte, Casse + subwoofer, Casse del monitor. I film 5.1/7.1 vengono mixati tenendo i bassi (LFE), che il mix normale butta via.
- **Uscita esclusiva** (facoltativa): suono originale senza mixer di Windows.
- **Ogni film ricorda** traccia audio, sottotitoli, ritardo sottotitoli e volume.
- **Sottotitoli anche con audio inglese**: si può spegnere in Impostazioni › Audio.

**Libreria**
- **Poster ufficiali** e titoli «Nome (anno)» da TMDB (chiave gratuita, Impostazioni › Libreria).
- **Aggiungi link**: tanti link insieme. Se un film c'è già, il link nuovo sostituisce quello scaduto e la ripresa resta uguale.
- **Stesso film, link nuovo**: anche dal player, se riapri un link nuovo dello stesso file riparte dal punto giusto.
- **Link scaduto** segnato sul poster; puoi salvare la pagina del sito per riaprirla al volo.
- **Episodio successivo** in automatico (stessa cartella o Libreria).
- Correggi titolo/poster, rinomina file come «Nome (anno)», statistiche del mese.

**Comodità**
- **Ctrl+K**: cerca un film o un comando.
- **Tasto destro sul video**: tracce, suono, velocità, cinema, telefono.
- **Modalità cinema** (tasto C): solo il film, senza menu.
- Barra e play nel **colore del film**. Animazione del logo all'avvio.

**Extra**
- **Torrent falsi**: avviso se dentro ci sono programmi (.exe, .lnk…) o archivi con password.
- **Windows Defender** controlla da solo i download che possono contenere programmi (zip, exe…).
- **Versione per telefono**: MP4 720p sotto 1,4 GB, audio nella lingua preferita, HDR convertito. Funziona da file e da link (tasto destro). Usa la GPU NVIDIA se c'è.
- **RTX Super Resolution** sui video ≤720p (da attivare anche nel Pannello NVIDIA).
- **Trasmetti alla TV** (DLNA, es. LG): l'audio DTS/TrueHD viene convertito in AC3, che le LG dal 2019 leggono.
- **Telecomando dal telefono**: inquadri un QR e comandi NOVA dal browser del telefono.
- **Backup completo** in un file zip (Impostazioni › Sistema).

## Novità della 2.1.1

- **Stream Turbo anche sui link senza estensione** (Cloudflare R2, CDN firmati, link "/hub/…?X-Amz-…"): prima questi link andavano con una sola connessione.
- **16 connessioni** di base e richieste più grandi lontano dal punto di visione: circa +30% di velocità a parità di rete.
- **Salti più rapidi**: dopo un salto le connessioni smettono subito di scaricare la zona vecchia.

## Novità della 2.1

- **Stream Turbo**: i link vengono letti con 8 connessioni insieme invece di una. Velocità piena anche quando il sito limita la singola connessione, salti molto più rapidi.
- **Link scaduti**: se un link scade mentre guardi, il film si ferma sul punto esatto; copi dal sito un link nuovo dello stesso film e riparte da solo. Nei download compare "Link scaduto" con il pulsante 🔗 (o basta copiare il link nuovo): riprende da dove era, senza perdere i GB scaricati. Se il link contiene la scadenza, la card mostra "link scade tra…".
- **Profilo 4K automatico**: sui video 4K niente filtri pesanti inutili, per non perdere fotogrammi.
- **Priorità al film**: mentre guardi qualcosa dalla rete, gli altri download e torrent rallentano.
- Tolto lo screenshot (pulsante e tasto S).

## Novità della 2.0

- **Home "Continua a guardare"**: il film da riprendere in grande con la sua copertina (presa dal video stesso, nessun servizio esterno) e le altre copertine sotto. Lo stesso riquadro compare nel Player quando non c'è niente in riproduzione.
- **Ripresa sempre esatta**, anche per i film visti in streaming da torrent.
- **Temi pronti**: Midnight, OLED nero, Ocean, Forest, Sakura, Chiaro. Sfondo sfocato con la copertina dietro al titolo del player.
- **Impostazioni nuove**: menu delle sezioni, ricerca, spiegazione di ogni opzione e ↺ per tornare al valore consigliato.
- **Più veloce**: le sezioni si caricano solo quando le apri; i download HTTP si adattano da soli se un server rifiuta troppe connessioni.
- **Torrent**: streaming più robusto (finestra di lettura di 48 MB, lettura dalla memoria se il file è bloccato), tracker aggiornati ogni giorno, indicatore "Porta aperta/chiusa" e pulsante per aprirla nel firewall.
- **NOVA.exe e installer**: doppio clic su `crea_exe.bat`.

## Creare NOVA.exe e l'installer

1. Fai prima `setup.bat` (una volta).
2. Doppio clic su **`crea_exe.bat`**: in 3-6 minuti crea `dist\NOVA\NOVA.exe` e `dist\NOVA-Setup.exe` (installa Inno Setup da solo con winget, se manca).
3. Installa con `NOVA-Setup.exe`: non chiede permessi di amministratore e crea le icone. Da lì in poi Python e la cartella del progetto non servono più.

## Installazione dalla cartella del progetto (una volta sola)

1. Estrai lo zip in una cartella fissa, per esempio `C:\NOVA` (non nella cartella Download temporanea).
2. Doppio clic su **`setup.bat`**. Fa tutto da solo:
   - installa Python 3.12 e il Visual C++ Runtime con winget, se mancano;
   - crea l'ambiente `.venv` e installa le librerie (PySide6, python-mpv, libtorrent, yt-dlp);
   - scarica in `bin\` i componenti nativi: **libmpv** (motore video), **aria2** (download veloci), **ffmpeg** (conversioni);
   - crea il collegamento **NOVA** sul Desktop e nel menu Start.
3. Apri NOVA dal Desktop (oppure `avvia.bat`).

Servono ~600 MB di spazio e una connessione internet durante il setup.

Facoltativo: *Impostazioni › Windows › Apri con NOVA* per avere NOVA in "Apri con", nel menu del tasto destro e come gestore dei link magnet.

## Cosa fa

| Sezione | Funzioni |
|---|---|
| **Player** | Tutti i formati (MKV, MP4, AVI, MOV, WEBM, TS/M2TS · HEVC, AV1, VP9 · DTS, TrueHD, E-AC3, FLAC). Cambio traccia audio/sottotitoli al volo, sottotitoli esterni (anche drag & drop), ritardo audio/sottotitoli, dimensione e posizione sottotitoli. Decodifica hardware D3D11, HDR, anteprima sulla barra, capitoli, velocità 0.25–4x, loop A-B, picture-in-picture, ripresa automatica. |
| **Stream** | Incolli un link (diretto, `.m3u8`, `.mpd` o pagina video) e parte. Cache 1 GB + 60 s di pre-lettura, riconnessione automatica, buffer visibile sulla barra, velocità di rete in tempo reale, qualità massima scelta da te. |
| **Download** | Fino a 16 connessioni per server (split fino a 32), coda, pausa/ripresa (anche dopo il riavvio), priorità, limiti di banda, barre animate con MB/s, media, tempo rimanente e grafico della velocità. Le pagine video passano da yt-dlp con scelta della qualità. Rileva i link copiati. |
| **Torrent** | `.torrent` o magnet, scelta dei file, download sequenziale e **▶ guarda mentre scarica**. A fine download: conversione MKV ↔ MP4 senza perdita (pochi secondi). Seeding configurabile. |
| **Libreria** | Cronologia con il punto in cui ti sei fermato. |
| **Impostazioni** | Tema, colore d'accento, livello animazioni, densità, dimensione testo (anteprima live), player, cache, cartelle, limiti, scorciatoie rimappabili, opzioni mpv avanzate. |

## Scorciatoie

| Tasto | Azione | Tasto | Azione |
|---|---|---|---|
| Spazio / clic | Play/Pausa | F / doppio clic | Schermo intero |
| ← → | ±5 s | ↑ ↓ | ±1 min |
| A | Audio successivo | V | Sottotitoli successivi |
| [ ] | Velocità | M | Muto |
| C | Modalità cinema | I | Statistiche (fps, frame persi) |
| L | Loop A-B | P | Picture-in-picture |
| Rotella | Volume | Esc | Esci da schermo intero / cinema |
| Ctrl+K | Cerca film e comandi | Tasto destro | Menu del video |
| Ctrl+F | Cerca una frase nei sottotitoli | F5 | Aggiorna la scheda |
| T | Boost video di bassa qualità | | |

## Se qualcosa non va

- **Un sito video non funziona più** → *Impostazioni › Avanzate › Aggiorna yt-dlp*.
- **Video che scatta** → premi `I` e guarda "Dropped frames". Controlla che *Decodifica hardware* sia attiva; se la GPU è debole, metti *Qualità immagine* su "Bilanciata".
- **Stream lento** → il collo di bottiglia è la connessione o il server: aumenta *Pre-lettura* e lascia caricare qualche secondo prima di premere play.
- **Errori** → log in `%APPDATA%\NOVA\logs`.
- **Reinstallare i componenti** → *Impostazioni › Avanzate › Aggiorna mpv, aria2 e ffmpeg*, oppure rilancia `setup.bat`.

## Note

- I contenuti protetti da DRM (Netflix, Prime Video, Disney+…) non sono supportati.
- Scarica e condividi via torrent solo contenuti che hai il diritto di scaricare.
- Dati e impostazioni: `%APPDATA%\NOVA`. Per disinstallare basta cancellare la cartella di NOVA e quella in `%APPDATA%`.
