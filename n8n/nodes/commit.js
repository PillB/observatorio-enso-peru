// Cuerpo del commit: el árbol recién creado, sin padre. La rama guarda solo
// la última copia (el historial no crece con cada corrida); el pipeline
// archiva lo que usa en la rama data-archive.
const info = $('Armar árbol').first().json;
return [{ json: { message: info.message, tree: $input.first().json.sha, parents: [] } }];
