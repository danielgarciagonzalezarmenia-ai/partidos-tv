$ErrorActionPreference = "Stop"
$root = "C:\Users\Daniel\Desktop\Partidos Tv"
$git = "C:\Program Files\Git\bin\git.exe"
$py  = "C:\Users\Daniel\AppData\Local\Programs\Python\Python313\python.exe"

Set-Location $root

# Descartar matches.json local (el scraper lo regenera) y traer remotos.
& $git checkout -- matches.json 2>&1 | Out-Null
& $git pull --rebase origin main 2>&1 | Out-Null

# Ejecutar el scraper (usa cookies.json y tu IP residencial).
& $py scripts\scraper.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "El scraper fallo con codigo $LASTEXITCODE"
    exit $LASTEXITCODE
}

# Publicar matches.json en GitHub (Pages lo sirve).
& $git add matches.json
& $git commit -m "auto: actualizar partidos $(Get-Date -Format u)" 2>&1 | Out-Null
& $git push origin main 2>&1 | Out-Null
Write-Host "Hecho."
