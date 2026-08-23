# Partidos TV

Web estática que muestra los partidos del día con su reproductor (iframe) y un
bot que los actualiza automáticamente cada día.

## Arquitectura
- **Frontend** (`index.html`, `app.js`, `styles.css`): lee `matches.json` y muestra los partidos.
- **Bot** (`scripts/scraper.py`): con Playwright abre 1win, extrae los partidos y captura el iframe firmado de top-parser.
- **GitHub Actions** (`.github/workflows/update.yml`): corre el bot cada día (cron 06:00 UTC) y commitea `matches.json`.
- **GitHub Pages**: sirve la web y da la URL pública.

## Puesta en marcha
1. Crea el repo en GitHub y sube este código.
2. En *Settings → Pages* elige la rama `main` y la carpeta `/ (root)`.
3. En *Settings → Actions → General → Workflow permissions* pon "Read and write".
4. La URL de Pages aparecerá en *Settings → Pages*.
5. (Opcional) Conecta el repo a Vercel para un despliegue adicional.

## Configurar el scraper
Edita `scripts/config.json`:
- `listing_url`: URL de la página de listado de partidos de 1win (si la hay).
- `match_urls`: lista manual de URLs de partidos (si no hay listado).

El paso que captura el iframe (`get_iframe` en `scripts/scraper.py`) depende del
flujo manual exacto para revelar el reproductor de top-parser y está marcado con
`TODO` para afinarlo.
