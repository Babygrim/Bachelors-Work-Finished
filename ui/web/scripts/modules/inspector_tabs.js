const SVG = (body) => `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" `
  + `stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;

const ICONS = {
  adjust: SVG('<line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="17" x2="20" y2="17"/>'
    + '<circle cx="9" cy="7" r="2.5" fill="currentColor"/><circle cx="15" cy="17" r="2.5" fill="currentColor"/>'),
  upscale: SVG('<polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/>'
    + '<line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/>'),
  realtime: SVG('<polygon points="13 2 4 14 12 14 11 22 20 10 12 10 13 2" fill="currentColor"/>'),
  frame: SVG('<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="11" r="1.6"/>'
    + '<polyline points="21 16 16 11 6 19"/>'),
};

const TABS = {
  image: [
    { id: 'adjust', label: 'Adjust', resettable: true },
    { id: 'upscale', label: 'Upscale', resettable: true },
  ],
  video: [
    { id: 'realtime', label: 'Real-time', resettable: false },
    { id: 'upscale', label: 'Upscale', resettable: true },
    { id: 'frame', label: 'Frame', resettable: false },
  ],
};

const EFFECT_DEFAULTS = { Brightness: 100, Color: 100, Contrast: 100, Sharpness: 100, Blur: 0, Inversion: false };

// Tab strip of the right-hand tool panel. Panels carry data-tab; for images they are the
// #effects-controls / #enhance-controls blocks, for videos the sections inside #video-controls.
export function createInspectorTabs({ strip, resetButton, onChange = () => {} }) {
  const remembered = { image: 'adjust', video: 'realtime' };
  let kind = null;

  const panels = (tabKind) => (tabKind === 'video'
    ? [...document.querySelectorAll('#video-controls .video-control-section')]
    : [...document.querySelectorAll('#effects-controls, #enhance-controls')]);

  function activeTab() {
    return TABS[kind]?.find((tab) => tab.id === remembered[kind]);
  }

  function applyActive() {
    if (!kind) return;
    const active = activeTab();
    strip.querySelectorAll('.inspector-tab').forEach((button) => {
      const selected = button.dataset.tab === active.id;
      button.classList.toggle('selected', selected);
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    for (const panel of panels(kind)) panel.hidden = panel.dataset.tab !== active.id;
    if (kind === 'video') {
      document.querySelectorAll('#effects-controls, #enhance-controls').forEach((panel) => { panel.hidden = true; });
    }
    resetButton.hidden = !active.resettable;
    onChange(active.id);
  }

  function select(id) {
    remembered[kind] = id;
    applyActive();
  }

  function render() {
    strip.replaceChildren(...TABS[kind].map((tab) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'inspector-tab';
      button.id = `inspector-tab-${tab.id}`;
      button.dataset.tab = tab.id;
      button.setAttribute('role', 'tab');
      button.innerHTML = `${ICONS[tab.id]}<span>${tab.label}</span><i class="tab-dot" hidden></i>`;
      button.addEventListener('click', () => select(tab.id));
      button.addEventListener('keydown', (event) => {
        const tabs = TABS[kind];
        const index = tabs.findIndex((item) => item.id === tab.id);
        const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
        if (!step) return;
        event.preventDefault();
        select(tabs[(index + step + tabs.length) % tabs.length].id);
        strip.querySelector('.inspector-tab.selected')?.focus();
      });
      return button;
    }));
  }

  function setDot(id, visible, title = '') {
    const dot = strip.querySelector(`[data-tab="${id}"] .tab-dot`);
    if (!dot) return;
    dot.hidden = !visible;
    dot.title = title;
  }

  function sync(next) {
    strip.hidden = !next.has_image;
    if (!next.has_image) return;
    const nextKind = next.kind === 'video' ? 'video' : 'image';
    if (nextKind !== kind) {
      kind = nextKind;
      render();
      applyActive();
    }
    if (kind === 'image') {
      const effects = next.settings.effects;
      const modified = Object.keys(EFFECT_DEFAULTS).some((key) => effects[key] !== EFFECT_DEFAULTS[key]);
      setDot('adjust', modified, 'Some adjustments differ from the defaults');
    } else {
      setDot('realtime', Boolean(next.video?.realtime_running), 'Real-time upscaling is running');
    }
  }

  // Scope sent to the backend's reset_module for the visible tab.
  const resetScope = () => activeTab()?.id ?? null;

  return { sync, select, resetScope };
}
