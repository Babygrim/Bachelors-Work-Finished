export function syncAdjustControls(next, pendingSettings) {
  const effects = next.settings.effects;
  document.querySelectorAll('.effect-slider').forEach((input) => {
    const name = input.dataset.setting;
    const value = pendingSettings.has(name) ? pendingSettings.get(name) : effects[name];
    if (document.activeElement !== input || pendingSettings.has(name)) input.value = value;
    const output = document.querySelector(`[data-output="${name}"]`);
    if (output) output.value = (Number(value) / 100).toFixed(2);
  });
  const inversion = pendingSettings.has('Inversion')
    ? pendingSettings.get('Inversion')
    : effects.Inversion;
  document.querySelector('#inversion').checked = inversion;
}

export function bindAdjustControls(setSetting, runAction) {
  document.querySelectorAll('.effect-slider').forEach((input) => input.addEventListener('input', () => {
    const output = document.querySelector(`[data-output="${input.dataset.setting}"]`);
    output.value = (Number(input.value) / 100).toFixed(2);
    setSetting(input.dataset.setting, Number(input.value));
  }));
  document.querySelector('#inversion').addEventListener('change', (event) => {
    setSetting('Inversion', event.target.checked);
  });
  document.querySelector('#denoise-button').addEventListener('click', () => {
    runAction('start_operation', 'denoise');
  });
}
