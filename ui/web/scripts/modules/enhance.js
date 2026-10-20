export function syncEnhanceControls(next, pendingSettings) {
  const enhancement = next.settings.enhancement;
  const factor = pendingSettings.has('factor')
    ? pendingSettings.get('factor')
    : enhancement.factor;
  document.querySelectorAll('[data-factor]').forEach((button) => {
    button.classList.toggle('selected', Number(button.dataset.factor) === factor);
  });
  document.querySelector('#keep-size').checked = pendingSettings.has('keep_size')
    ? pendingSettings.get('keep_size')
    : enhancement.keep_size;
  document.querySelector('#face-restoration').checked = pendingSettings.has('face_restoration')
    ? pendingSettings.get('face_restoration')
    : enhancement.face_restoration;

  const model = document.querySelector('#model-select');
  if (model.dataset.factor !== String(enhancement.factor)) {
    model.replaceChildren(...next.models.map((name) => new Option(name, name)));
    model.dataset.factor = String(enhancement.factor);
  }
  model.value = pendingSettings.has('model')
    ? pendingSettings.get('model')
    : enhancement.model;
  model.disabled = !next.models.length;
}

export function bindEnhanceControls(setSetting, runAction) {
  document.querySelectorAll('[data-factor]').forEach((button) => {
    button.addEventListener('click', () => setSetting('factor', Number(button.dataset.factor)));
  });
  document.querySelector('#model-select').addEventListener('change', (event) => {
    setSetting('model', event.target.value);
  });
  document.querySelector('#keep-size').addEventListener('change', (event) => {
    setSetting('keep_size', event.target.checked);
  });
  document.querySelector('#face-restoration').addEventListener('change', (event) => {
    setSetting('face_restoration', event.target.checked);
  });
  document.querySelector('#upscale-button').addEventListener('click', () => {
    runAction('start_operation', 'upscale');
  });
}
