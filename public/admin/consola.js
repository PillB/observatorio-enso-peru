// Común a las tres consolas (lugares, documentos, analítica): el tema que la persona eligió en el sitio público.
try {
  const theme = localStorage.getItem('enso-theme');
  if (theme === 'dark' || theme === 'light') document.documentElement.dataset.theme = theme;
} catch { /* almacenamiento bloqueado: queda el tema del sistema */ }
