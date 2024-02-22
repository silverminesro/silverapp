// Funkcia na aktualizáciu stránky
function aktualizujStranku() {
    // Znovu načítajte aktuálnu stránku
    location.reload();

    // Zápis do logu
    console.log('Stránka bola aktualizovaná.');

    // Spustite funkciu znova po 10 minútach (600 000 milisekúnd)
    setTimeout(aktualizujStranku, 600000);
}

// Spustite funkciu na aktualizáciu stránky po načítaní stránky
window.onload = function() {
    setTimeout(aktualizujStranku, 600000);
};
