# Локальный HTTP-сервер для калькулятора (PWA и Service Worker)
# Запуск: правый клик → «Выполнить с PowerShell» или: .\serve.ps1

$Port = 8080
$Root = $PSScriptRoot

Write-Host "Сервер: http://localhost:$Port" -ForegroundColor Green
Write-Host "Папка:  $Root" -ForegroundColor Gray
Write-Host "Остановка: Ctrl+C" -ForegroundColor Gray
Write-Host ""

Set-Location $Root

if (Get-Command python -ErrorAction SilentlyContinue) {
    python -m http.server $Port
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    py -m http.server $Port
} else {
    Write-Host "Python не найден. Откройте index.html двойным щелчком или установите Python 3." -ForegroundColor Yellow
    Read-Host "Нажмите Enter"
}
