// Applies a saved colour theme before first paint (external file so the CSP can forbid inline scripts).
try { var t = localStorage.getItem('ad.theme'); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
