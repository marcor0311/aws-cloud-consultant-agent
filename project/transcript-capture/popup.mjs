async function refresh() {
  const {captures = [], activeTab, transcript = []} = await chrome.storage.local.get(['captures', 'activeTab', 'transcript']);
  document.querySelector('#active').textContent = activeTab == null ? 'Sin captura activa.' :
    (transcript.length ? `Meet abierto · ${transcript.length} intervenciones guardadas. Evitá recargar la pestaña.` : 'Meet abierto · todavía no se guardó texto. Revisá los subtítulos y hablá unos segundos.');
  const list = document.querySelector('#captures');
  list.replaceChildren();
  for (const capture of [...captures].reverse()) {
    const item = document.createElement('li');
    const labels = {pending: 'Pendiente de envío', delivered: 'Recibida por el backend', incomplete: 'Incompleta: requiere revisión'};
    item.textContent = `${capture.meetingUrl} — ${labels[capture.status] || capture.status}`;
    const download = document.createElement('button');
    download.textContent = 'Guardar copia JSON';
    download.onclick = () => {
      const url = URL.createObjectURL(new Blob([JSON.stringify(capture, null, 2)], {type: 'application/json'}));
      chrome.downloads.download({url, filename: `meeting-${capture.captureId}.json`}).finally(() => URL.revokeObjectURL(url));
    };
    item.append(document.createElement('br'), download);
    list.append(item);
  }
}
document.querySelector('#retry').onclick = async () => {
  await chrome.runtime.sendMessage({type: 'consulting_retry'});
  await refresh();
};
await refresh();
